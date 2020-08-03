# coding=utf-8
# Copyright 2018 The Google AI Language Team Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""BERT finetuning runner."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import collections
import csv
import os
import random
import re

import tensorflow as tf
from bert import modeling
from bert import optimization
from bert import tokenization

flags = tf.flags

FLAGS = flags.FLAGS

## Required parameters
flags.DEFINE_string(
    "data_dir", 'data',
    "The input data dir. Should contain the .tsv files (or other data files) "
    "for the task.")

flags.DEFINE_string(
    "bert_config_file", 'uncased_L-12_H-768_A-12/bert_config.json',
    "The config json file corresponding to the pre-trained BERT model. "
    "This specifies the model architecture.")

flags.DEFINE_string("task_name", 'adv', "The name of the task to train.")

flags.DEFINE_string("vocab_file", 'uncased_L-12_H-768_A-12/vocab.txt',
                    "The vocabulary file that the BERT model was trained on.")

flags.DEFINE_string(
    "output_dir", 'output_adv_mimic_dp_512_ere3',
    "The output directory where the model checkpoints will be written.")

## Other parameters
# 80% of i2b2
flags.DEFINE_integer(
    "number_training_instance", 1500,
    "Number of training instance to make for Adversarial Classifier")

flags.DEFINE_string(
    "init_checkpoint", 'uncased_L-12_H-768_A-12/bert_model.ckpt',
    "Initial checkpoint (usually from a pre-trained BERT model).")

flags.DEFINE_bool(
    "do_lower_case", True,
    "Whether to lower case the input text. Should be True for uncased "
    "models and False for cased models.")

flags.DEFINE_integer(
    "max_seq_length", 512,
    "The maximum total input sequence length after WordPiece tokenization. "
    "Sequences longer than this will be truncated, and sequences shorter "
    "than this will be padded.")

flags.DEFINE_bool("do_train", True, "Whether to run training.")

flags.DEFINE_bool("do_eval", True, "Whether to run eval on the dev set.")

flags.DEFINE_bool(
    "do_predict", False,
    "Whether to run the model in inference mode on the test set.")

flags.DEFINE_integer("train_batch_size", 6, "Total batch size for training.")

flags.DEFINE_integer("eval_batch_size", 6, "Total batch size for eval.")

flags.DEFINE_integer("predict_batch_size", 6, "Total batch size for predict.")

flags.DEFINE_float("learning_rate", 5e-5, "The initial learning rate for Adam.")

flags.DEFINE_float("num_train_epochs", 10,
                   "Total number of training epochs to perform.")

flags.DEFINE_float(
    "warmup_proportion", 0.1,
    "Proportion of training to perform linear learning rate warmup for. "
    "E.g., 0.1 = 10% of training.")

flags.DEFINE_integer("save_checkpoints_steps", 1000,
                     "How often to save the model checkpoint.")

flags.DEFINE_integer("iterations_per_loop", 1000,
                     "How many steps to make in each estimator call.")

flags.DEFINE_bool("use_tpu", False, "Whether to use TPU or GPU/CPU.")

tf.flags.DEFINE_string(
    "tpu_name", None,
    "The Cloud TPU to use for training. This should be either the name "
    "used when creating the Cloud TPU, or a grpc://ip.address.of.tpu:8470 "
    "url.")

tf.flags.DEFINE_string(
    "tpu_zone", None,
    "[Optional] GCE zone where the Cloud TPU is located in. If not "
    "specified, we will attempt to automatically detect the GCE project from "
    "metadata.")

tf.flags.DEFINE_string(
    "gcp_project", None,
    "[Optional] Project name for the Cloud TPU-enabled project. If not "
    "specified, we will attempt to automatically detect the GCE project from "
    "metadata.")

tf.flags.DEFINE_string("master", None, "[Optional] TensorFlow master URL.")

flags.DEFINE_integer(
    "num_tpu_cores", 8,
    "Only used if `use_tpu` is True. Total number of TPU cores to use.")


class InputExample(object):
    """A single training/test example for simple sequence classification."""

    def __init__(self, guid, text_a, text_b=None, label=None):
        """Constructs a InputExample.

        Args:
          guid: Unique id for the example.
          text_a: string. The untokenized text of the first sequence. For single
            sequence tasks, only this sequence must be specified.
          text_b: (Optional) string. The untokenized text of the second sequence.
            Only must be specified for sequence pair tasks.
          label: (Optional) string. The label of the example. This should be
            specified for train and dev examples, but not for test examples.
        """
        self.guid = guid
        self.text_a = text_a
        self.text_b = text_b
        self.label = label


class PaddingInputExample(object):
    """Fake example so the num input examples is a multiple of the batch size.

    When running eval/predict on the TPU, we need to pad the number of examples
    to be a multiple of the batch size, because the TPU requires a fixed batch
    size. The alternative is to drop the last batch, which is bad because it means
    the entire output data won't be generated.

    We use this class instead of `None` because treating `None` as padding
    battches could cause silent errors.
    """


class InputFeatures(object):
    """A single set of features of data."""

    def __init__(self,
                 input_ids,
                 input_mask,
                 segment_ids,
                 label_id,
                 is_real_example=True):
        self.input_ids = input_ids
        self.input_mask = input_mask
        self.segment_ids = segment_ids
        self.label_id = label_id
        self.is_real_example = is_real_example


class DataProcessor(object):
    """Base class for data converters for sequence classification data sets."""

    def clean_text(self, text):
        text = re.sub(r'(\[\*{2}[0-9\-\sa-zA-Z\(\)\/]+\*{2}\])', '', text)
        # text = re.sub(r'[^\\n\.][A-Z\sa-z]+\:', '', text)
        text = re.sub(r'\n+', ' ', text)
        text = re.sub(r'\s\d\.\s', ' ', text)
        text = re.sub(r'[\\.]\s\#[\\.]', ' ', text)
        text = re.sub(r'\#', ' ', text)
        text = re.sub(r'[\_\-]', ' ', text)
        text = re.sub(r'[\\.][\s\W][\\.]', ' ', text)
        text = re.sub(r'[\\.]\s\d[\\.]', ' ', text)
        text = re.sub(r'[^\w]', ' ', text)
        text = re.sub(r'\s{2,}', ' ', text)
        return text

    def get_train_examples(self, data_dir):
        """Gets a collection of `InputExample`s for the train set."""
        raise NotImplementedError()

    def get_dev_examples(self, data_dir):
        """Gets a collection of `InputExample`s for the dev set."""
        raise NotImplementedError()

    def get_AdvSuccess_examples(self, data_dir):
        """Gets a collection of `InputExample`s for the dev set."""
        raise NotImplementedError()

    def get_test_examples(self, data_dir):
        """Gets a collection of `InputExample`s for prediction."""
        raise NotImplementedError()

    def get_labels(self):
        """Gets the list of labels for this data set."""
        raise NotImplementedError()

    @classmethod
    def _read_tsv(cls, input_file, quotechar=None):
        """Reads a tab separated value file."""
        with tf.gfile.Open(input_file, "r") as f:
            reader = csv.reader(f, delimiter="\t", quotechar=quotechar)
            lines = []
            for line in reader:
                lines.append(line)
            return lines

    @classmethod
    def _read_txt(cls, input_file, quotechar=None):
        """Reads a tab separated value file."""
        with tf.gfile.Open(input_file, "r") as f:
            reader = csv.reader(f, delimiter="\t", quotechar=quotechar)
            lines = []
            for line in reader:
                lines.append(line)
            return lines


class ADVProcessor(DataProcessor):
    """Processor for the MRPC data set (GLUE version)."""

    def get_i2b2_gen_text(self, data_dir, type='train', is_adv=False, label=1):
        line = []
        main_path = os.path.join(data_dir, 'i2b2_generated_deid')
        # else:
        #     main_path = os.path.join(data_dir, 'generated_124')
        # files = os.listdir(main_path)
        # file = random.choice(files)
        with open(os.path.join(main_path, 'i2b2_generated_deid.txt'), 'r') as file:
            docs = file.read().split('=' * 20 + '\n')
            random.shuffle(docs)
            if type == 'train':
                docs = docs[:FLAGS.number_training_instance]
            else:
                docs = docs[
                       FLAGS.number_training_instance:int(FLAGS.number_training_instance * 1.2)]  # 20% of 190 = 1.2
            for doc in docs:
                # while len(text_a) - FLAGS.max_seq_length - 5 < 0:
                doc = ' '.join(l for l in doc.split("\n")[1:])
                text_a = self.get_text(self.clean_text(doc))
                if is_adv and type == 'train':
                    label = random.randint(0, 1)
                line.append([text_a.lower(), '', label])  #

        return line

    def get_text(self, text_a):
        text_a = text_a.split()
        start_pos = 0#random.randint(0, len(text_a))
        # text_a = text_a[start_pos:start_pos + FLAGS.max_seq_length - 5]
        text_a = text_a[start_pos:len(text_a) if (start_pos + FLAGS.max_seq_length - 5) > len(
            text_a) else start_pos + FLAGS.max_seq_length - 5]
        text_a = ' '.join(t.strip() for t in text_a)
        return text_a.strip().lower()

    def get_i2b2_original(self, data_dir, type='train', is_adv=False, label=0):
        line = []
        files = os.listdir(os.path.join(data_dir, 'i2b2_deid_data'))
        random.shuffle(files)
        if type == 'train':
            files = files[:FLAGS.number_training_instance]  # [:int(0.8 * len(files))]
        else:
            files = files[FLAGS.number_training_instance:int(
                FLAGS.number_training_instance * 1.2)]  # [int(0.8 * len(files)):]

        # while len(text_a) - FLAGS.max_seq_length - 5 < 0:
        # file = random.choice(files)
        for file in files:
            with open(os.path.join(data_dir, 'i2b2_deid_data', file), 'r') as rfile:
                doc = ' '.join(l for l in rfile.read().split('\n')[1:])
                text_a = self.get_text(self.clean_text(doc))

                if is_adv and type == 'train':
                    label = random.randint(0, 1)
                line.append([text_a.lower(), '', label])  #
        random.shuffle(line)
        return line

    def get_mimic_text(self, data_dir, size, type='train'):
        line = []
        # labels = np.random.randint(2, size=size)
        for i in range(size):
            text_a = ''

            label = i % 2 if type == 'train' else random.choice([0, 1])
            # if i > int(size * .75):
            #     label = 0
            if label <= 1 :  # or random.choice([0, 1, 2]) == 2:
                # if type == 'train':
                main_path = os.path.join(data_dir, 'mimic_dp')
                # else:
                #     main_path = os.path.join(data_dir, 'generated_124')
                files = os.listdir(main_path)
                file = random.choice(files)
                with open(os.path.join(main_path, file), 'r') as file:
                    docs = file.read().split('=' * 20 + '\n')
                    # random.shuffle(docs)
                    if type == 'train':
                        docs = docs[:int(len(docs) * .7)]
                    else:
                        docs = docs[int(len(docs) * .7):]
                    doc = docs[(i // 2) % len(docs)]
                    # doc = random.choice(docs)
                    doc = ' '.join(l for l in doc.split("\n")[1:])
                    text_a = self.get_text(self.clean_text(doc))
            else:
                files = os.listdir(os.path.join(data_dir, 'MIMICIII_original_sep'))
                # subdir = random.choice(files)
                subdir = files[i%len(files)]
                files = os.listdir(os.path.join(data_dir, 'MIMICIII_original_sep', subdir))
                if type == 'train':
                    files = files[:int(len(files) * .7)]
                else:
                    files = files[int(len(files) * .7):]
                # random.shuffle(files)
                # file = random.choice(files)
                file = files[(i // 2 + 1) % len(files)]
                with open(os.path.join(data_dir, 'MIMICIII_original_sep', subdir, file), 'r') as file:
                    doc = ' '.join(l for l in file.read().split('\n')[1:])
                    text_a = self.get_text(self.clean_text(doc))

            line.append([text_a, '', label])  #
        # for i in range(5):
        #     print(str(line[i][2]) + '==>' + line[i][0])
        random.shuffle(line)
        # print(100 * numberOnes / size)
        return line

    def getGenAllMIMICADV2(self, data_dir):
        line = []
        label = 0
        folder = os.listdir(os.path.join(data_dir, 'MIMICIII_original_sep'))
        for subdir in folder:
            files = os.listdir(os.path.join(data_dir, 'MIMICIII_original_sep', subdir))
            for file in files:
                with open(os.path.join(data_dir, 'MIMICIII_original_sep', subdir, file), 'r') as file:
                    doc = ' '.join(l for l in file.read().split('\n')[1:])
                    text_a = self.get_text(self.clean_text(doc))
                    line.append([text_a.lower(), '', label])  #
        random.shuffle(line)
        return line

    def getGenAllMIMICADV(self, data_dir):
        line = []
        # labels = np.random.randint(2, size=size)

        text_a = ''
        # label = random.choice([0, 1])
        label = 1
        # if i > int(size * .75):
        #     label = 0
        # if label == 1:  # or random.choice([0, 1, 2]) == 2:
        # if type == 'train':
        main_path = os.path.join(data_dir, 'mimic_dp')
        # else:
        #     main_path = os.path.join(data_dir, 'generated_124')
        files = os.listdir(main_path)
        for file in files:
            with open(os.path.join(main_path, file), 'r') as file:
                docs = file.read().split('=' * 20 + '\n')
                random.shuffle(docs)
                for doc in docs:
                    doc = ' '.join(l for l in doc.split("\n")[1:])
                    text_a = self.get_text(self.clean_text(doc))
                    line.append([text_a.lower(), '', label])  #

        # for i in range(5):
        #     print(str(line[i][2]) + '==>' + line[i][0])
        random.shuffle(line)
        # print(100 * numberOnes / size)
        return line

    def getGenAlli2b2ADV(self, data_dir):
        line = []
        main_path = os.path.join(data_dir, 'i2b2_generated_deid')
        # else:
        #     main_path = os.path.join(data_dir, 'generated_124')
        # files = os.listdir(main_path)
        # file = random.choice(files)
        with open(os.path.join(main_path, 'i2b2_generated_deid.txt'), 'r') as file:
            docs = file.read().split('=' * 20 + '\n')
            for doc in docs:
                # while len(text_a) - FLAGS.max_seq_length - 5 < 0:

                doc = ' '.join(l.strip() for l in doc.split("\n")[1:])
                text_a = self.get_text(self.clean_text(doc))
                line.append([text_a.lower(), '', 1])  #
        random.shuffle(line)
        return line

    def getLines_i2b2(self, data_dir, type='train'):
        line = self.get_i2b2_original(data_dir, type, is_adv=True)

        if type != 'train':
            line += self.get_i2b2_gen_text(data_dir, type, is_adv=False)
        random.shuffle(line)
        # print(100 * numberOnes / size)
        return line

    def get_train_examples(self, data_dir):
        """See base class."""
        # return self._create_examples(self.getLines_i2b2(data_dir, type="train"), "train")
        return self._create_examples(
            self.get_mimic_text(data_dir, int(.8 * FLAGS.number_training_instance), type="train"),
            "train")

    def get_dev_examples(self, data_dir):
        """See base class."""
        # return self._create_examples(self.getLines_i2b2(data_dir, type='test'), "dev")
        return self._create_examples(
            self.get_mimic_text(data_dir, int(FLAGS.number_training_instance * .2), type='dev'), "dev")

    def get_AdvSuccess_examples(self, data_dir):
        """See base class."""
        return self._create_examples(self.getGenAllMIMICADV(data_dir), "dev")

    def get_test_examples(self, data_dir):
        """See base class."""
        return self._create_examples(self.getGenAlli2b2ADV(data_dir), "test")

    def get_labels(self):
        """See base class."""
        return [0, 1]

    def _create_examples(self, data, set_type):
        """Creates examples for the training and dev sets."""
        examples = []
        for (i, line) in enumerate(data):
            # if i == 0:
            #     continue
            guid = "%s-%s" % (set_type, i)
            text_a = tokenization.convert_to_unicode(line[0])
            text_b = tokenization.convert_to_unicode(line[1])
            # if set_type == "test":
            #     label = "0"
            # else:
            label = line[2]  # tokenization.convert_to_unicode(str(line[2]))
            examples.append(
                InputExample(guid=guid, text_a=text_a, text_b=text_b, label=label))
        return examples

    def _create_examples_old(self, lines, set_type):
        """Creates examples for the training and dev sets."""
        examples = []
        for (i, line) in enumerate(lines):
            if i == 0:
                continue
            guid = "%s-%s" % (set_type, i)
            text_a = tokenization.convert_to_unicode(line[3])
            text_b = tokenization.convert_to_unicode(line[4])
            if set_type == "test":
                label = "0"
            else:
                label = tokenization.convert_to_unicode(line[0])
            examples.append(
                InputExample(guid=guid, text_a=text_a, text_b=text_b, label=label))
        return examples


def convert_single_example(ex_index, example, label_list, max_seq_length,
                           tokenizer):
    """Converts a single `InputExample` into a single `InputFeatures`."""

    if isinstance(example, PaddingInputExample):
        return InputFeatures(
            input_ids=[0] * max_seq_length,
            input_mask=[0] * max_seq_length,
            segment_ids=[0] * max_seq_length,
            label_id=0,
            is_real_example=False)

    label_map = {}
    for (i, label) in enumerate(label_list):
        label_map[label] = i

    tokens_a = tokenizer.tokenize(example.text_a)
    tokens_b = None
    if example.text_b:
        tokens_b = tokenizer.tokenize(example.text_b)

    if tokens_b:
        # Modifies `tokens_a` and `tokens_b` in place so that the total
        # length is less than the specified length.
        # Account for [CLS], [SEP], [SEP] with "- 3"
        _truncate_seq_pair(tokens_a, tokens_b, max_seq_length - 3)
    else:
        # Account for [CLS] and [SEP] with "- 2"
        if len(tokens_a) > max_seq_length - 2:
            tokens_a = tokens_a[0:(max_seq_length - 2)]

    # The convention in BERT is:
    # (a) For sequence pairs:
    #  tokens:   [CLS] is this jack ##son ##ville ? [SEP] no it is not . [SEP]
    #  type_ids: 0     0  0    0    0     0       0 0     1  1  1  1   1 1
    # (b) For single sequences:
    #  tokens:   [CLS] the dog is hairy . [SEP]
    #  type_ids: 0     0   0   0  0     0 0
    #
    # Where "type_ids" are used to indicate whether this is the first
    # sequence or the second sequence. The embedding vectors for `type=0` and
    # `type=1` were learned during pre-training and are added to the wordpiece
    # embedding vector (and position vector). This is not *strictly* necessary
    # since the [SEP] token unambiguously separates the sequences, but it makes
    # it easier for the model to learn the concept of sequences.
    #
    # For classification tasks, the first vector (corresponding to [CLS]) is
    # used as the "sentence vector". Note that this only makes sense because
    # the entire model is fine-tuned.
    tokens = []
    segment_ids = []
    tokens.append("[CLS]")
    segment_ids.append(0)
    for token in tokens_a:
        tokens.append(token)
        segment_ids.append(0)
    tokens.append("[SEP]")
    segment_ids.append(0)

    if tokens_b:
        for token in tokens_b:
            tokens.append(token)
            segment_ids.append(1)
        tokens.append("[SEP]")
        segment_ids.append(1)

    input_ids = tokenizer.convert_tokens_to_ids(tokens)

    # The mask has 1 for real tokens and 0 for padding tokens. Only real
    # tokens are attended to.
    input_mask = [1] * len(input_ids)

    # Zero-pad up to the sequence length.
    while len(input_ids) < max_seq_length:
        input_ids.append(0)
        input_mask.append(0)
        segment_ids.append(0)

    assert len(input_ids) == max_seq_length
    assert len(input_mask) == max_seq_length
    assert len(segment_ids) == max_seq_length

    label_id = label_map[example.label]
    if ex_index < 5:
        tf.logging.info("*** Example ***")
        tf.logging.info("guid: %s" % (example.guid))
        tf.logging.info("tokens: %s" % " ".join(
            [tokenization.printable_text(x) for x in tokens]))
        tf.logging.info("input_ids: %s" % " ".join([str(x) for x in input_ids]))
        tf.logging.info("input_mask: %s" % " ".join([str(x) for x in input_mask]))
        tf.logging.info("segment_ids: %s" % " ".join([str(x) for x in segment_ids]))
        tf.logging.info("label: %s (id = %d)" % (example.label, label_id))

    feature = InputFeatures(
        input_ids=input_ids,
        input_mask=input_mask,
        segment_ids=segment_ids,
        label_id=label_id,
        is_real_example=True)
    return feature


def file_based_convert_examples_to_features(
        examples, label_list, max_seq_length, tokenizer, output_file):
    """Convert a set of `InputExample`s to a TFRecord file."""

    writer = tf.python_io.TFRecordWriter(output_file)

    for (ex_index, example) in enumerate(examples):
        if ex_index % 10000 == 0:
            tf.logging.info("Writing example %d of %d" % (ex_index, len(examples)))

        feature = convert_single_example(ex_index, example, label_list,
                                         max_seq_length, tokenizer)

        def create_int_feature(values):
            f = tf.train.Feature(int64_list=tf.train.Int64List(value=list(values)))
            return f

        features = collections.OrderedDict()
        features["input_ids"] = create_int_feature(feature.input_ids)
        features["input_mask"] = create_int_feature(feature.input_mask)
        features["segment_ids"] = create_int_feature(feature.segment_ids)
        features["label_ids"] = create_int_feature([feature.label_id])
        features["is_real_example"] = create_int_feature(
            [int(feature.is_real_example)])

        tf_example = tf.train.Example(features=tf.train.Features(feature=features))
        writer.write(tf_example.SerializeToString())
    writer.close()


def file_based_input_fn_builder(input_file, seq_length, is_training,
                                drop_remainder):
    """Creates an `input_fn` closure to be passed to TPUEstimator."""

    name_to_features = {
        "input_ids": tf.FixedLenFeature([seq_length], tf.int64),
        "input_mask": tf.FixedLenFeature([seq_length], tf.int64),
        "segment_ids": tf.FixedLenFeature([seq_length], tf.int64),
        "label_ids": tf.FixedLenFeature([], tf.int64),
        "is_real_example": tf.FixedLenFeature([], tf.int64),
    }

    def _decode_record(record, name_to_features):
        """Decodes a record to a TensorFlow example."""
        example = tf.parse_single_example(record, name_to_features)

        # tf.Example only supports tf.int64, but the TPU only supports tf.int32.
        # So cast all int64 to int32.
        for name in list(example.keys()):
            t = example[name]
            if t.dtype == tf.int64:
                t = tf.to_int32(t)
            example[name] = t

        return example

    def input_fn(params):
        """The actual input function."""
        batch_size = params["batch_size"]

        # For training, we want a lot of parallel reading and shuffling.
        # For eval, we want no shuffling and parallel reading doesn't matter.
        d = tf.data.TFRecordDataset(input_file)
        if is_training:
            d = d.repeat()
            d = d.shuffle(buffer_size=100)

        d = d.apply(
            tf.contrib.data.map_and_batch(
                lambda record: _decode_record(record, name_to_features),
                batch_size=batch_size,
                drop_remainder=drop_remainder))

        return d

    return input_fn


def _truncate_seq_pair(tokens_a, tokens_b, max_length):
    """Truncates a sequence pair in place to the maximum length."""

    # This is a simple heuristic which will always truncate the longer sequence
    # one token at a time. This makes more sense than truncating an equal percent
    # of tokens from each, since if one sequence is very short then each token
    # that's truncated likely contains more information than a longer sequence.
    while True:
        total_length = len(tokens_a) + len(tokens_b)
        if total_length <= max_length:
            break
        if len(tokens_a) > len(tokens_b):
            tokens_a.pop()
        else:
            tokens_b.pop()


def create_model(bert_config, is_training, input_ids, input_mask, segment_ids,
                 labels, num_labels, use_one_hot_embeddings):
    """Creates a classification model."""
    model = modeling.BertModel(
        config=bert_config,
        is_training=is_training,
        input_ids=input_ids,
        input_mask=input_mask,
        token_type_ids=segment_ids,
        use_one_hot_embeddings=use_one_hot_embeddings)

    # In the demo, we are doing a simple classification task on the entire
    # segment.
    #
    # If you want to use the token-level output, use model.get_sequence_output()
    # instead.
    output_layer = model.get_pooled_output()

    hidden_size = output_layer.shape[-1].value

    output_weights = tf.get_variable(
        "output_weights", [num_labels, hidden_size],
        initializer=tf.truncated_normal_initializer(stddev=0.02))

    output_bias = tf.get_variable(
        "output_bias", [num_labels], initializer=tf.zeros_initializer())

    with tf.variable_scope("loss"):
        if is_training:
            # I.e., 0.1 dropout
            output_layer = tf.nn.dropout(output_layer, keep_prob=0.5)

        logits = tf.matmul(output_layer, output_weights, transpose_b=True)
        logits = tf.nn.bias_add(logits, output_bias)
        probabilities = tf.nn.softmax(logits, axis=-1)
        log_probs = tf.nn.log_softmax(logits, axis=-1)

        one_hot_labels = tf.one_hot(labels, depth=num_labels, dtype=tf.float32)

        per_example_loss = -tf.reduce_sum(one_hot_labels * log_probs, axis=-1)
        loss = tf.reduce_mean(per_example_loss)

        return (loss, per_example_loss, logits, probabilities)


def metric_fn(per_example_loss, label_ids, logits, is_real_example):
    predictions = tf.argmax(logits, axis=-1, output_type=tf.int32)
    accuracy = tf.metrics.accuracy(labels=label_ids, predictions=predictions, weights=is_real_example)
    loss = tf.metrics.mean(values=per_example_loss, weights=is_real_example)
    return {
        "eval_accuracy": accuracy,
        "eval_loss": loss,
    }


def model_fn_builder(bert_config, num_labels, init_checkpoint, learning_rate,
                     num_train_steps, num_warmup_steps, use_tpu,
                     use_one_hot_embeddings):
    """Returns `model_fn` closure for TPUEstimator."""

    def model_fn(features, labels, mode, params):  # pylint: disable=unused-argument
        """The `model_fn` for TPUEstimator."""

        tf.logging.info("*** Features ***")
        for name in sorted(features.keys()):
            tf.logging.info("  name = %s, shape = %s" % (name, features[name].shape))

        input_ids = features["input_ids"]
        input_mask = features["input_mask"]
        segment_ids = features["segment_ids"]
        label_ids = features["label_ids"]
        is_real_example = None
        if "is_real_example" in features:
            is_real_example = tf.cast(features["is_real_example"], dtype=tf.float32)
        else:
            is_real_example = tf.ones(tf.shape(label_ids), dtype=tf.float32)

        is_training = (mode == tf.estimator.ModeKeys.TRAIN)

        (total_loss, per_example_loss, logits, probabilities) = create_model(
            bert_config, is_training, input_ids, input_mask, segment_ids, label_ids,
            num_labels, use_one_hot_embeddings)

        tvars = tf.trainable_variables()
        initialized_variable_names = {}
        scaffold_fn = None
        if init_checkpoint:
            (assignment_map, initialized_variable_names
             ) = modeling.get_assignment_map_from_checkpoint(tvars, init_checkpoint)
            if use_tpu:

                def tpu_scaffold():
                    tf.train.init_from_checkpoint(init_checkpoint, assignment_map)
                    return tf.train.Scaffold()

                scaffold_fn = tpu_scaffold
            else:
                tf.train.init_from_checkpoint(init_checkpoint, assignment_map)

        # tf.logging.info("**** Trainable Variables ****")
        # for var in tvars:
        # init_string = ""
        # if var.name in initialized_variable_names:
        #     init_string = ", *INIT_FROM_CKPT*"
        # tf.logging.info("  name = %s, shape = %s%s", var.name, var.shape,
        #                 init_string)

        output_spec = None
        if mode == tf.estimator.ModeKeys.TRAIN:

            train_op = optimization.create_optimizer(
                total_loss, learning_rate, num_train_steps, num_warmup_steps, use_tpu)
            predictions = tf.argmax(logits, axis=-1, output_type=tf.int32)
            # cmetrics = metrics.streaming_confusion_matrix_with_current_cm(label_ids, predictions, num_labels,
            #                                                               weights=input_mask)
            # current_cm = cmetrics[2]
            # TP = tf.Variable(0, dtype=tf.float32)
            # FN = tf.Variable(0, dtype=tf.float32)
            # FP = tf.Variable(0, dtype=tf.float32)
            # for i in range(num_labels - 1):
            #     TP = TP + current_cm[i][i]
            #     for j in range(num_labels - 1):
            #         if i != j:
            #             FN = FN + current_cm[j][i]
            #             FP = FP + current_cm[i][j]
            #
            # accuracy = tf.metrics.accuracy(labels=label_ids, predictions=predictions, weights=is_real_example)
            #
            # logging_hook = tf.train.LoggingTensorHook({"loss": total_loss, "TP": TP, "FN": FN, "accuracy": accuracy},
            #                                           every_n_iter=25)
            accuracy = tf.metrics.accuracy(labels=label_ids, predictions=predictions)
            #
            logging_hook = tf.train.LoggingTensorHook({"loss": total_loss, "accuracy": accuracy[1]}, every_n_iter=25)



            output_spec = tf.contrib.tpu.TPUEstimatorSpec(
                mode=mode,
                loss=total_loss,
                training_hooks=[logging_hook],
                train_op=train_op,
                scaffold_fn=scaffold_fn)
        elif mode == tf.estimator.ModeKeys.EVAL:

            eval_metrics = (metric_fn,
                            [per_example_loss, label_ids, logits, is_real_example])
            output_spec = tf.contrib.tpu.TPUEstimatorSpec(
                mode=mode,
                loss=total_loss,
                eval_metrics=eval_metrics,
                scaffold_fn=scaffold_fn)
        else:
            output_spec = tf.contrib.tpu.TPUEstimatorSpec(
                mode=mode,
                predictions={"probabilities": probabilities},
                scaffold_fn=scaffold_fn)
        return output_spec

    return model_fn


# This function is not used by this file but is still used by the Colab and
# people who depend on it.
def input_fn_builder(features, seq_length, is_training, drop_remainder):
    """Creates an `input_fn` closure to be passed to TPUEstimator."""

    all_input_ids = []
    all_input_mask = []
    all_segment_ids = []
    all_label_ids = []

    for feature in features:
        all_input_ids.append(feature.input_ids)
        all_input_mask.append(feature.input_mask)
        all_segment_ids.append(feature.segment_ids)
        all_label_ids.append(feature.label_id)

    def input_fn(params):
        """The actual input function."""
        batch_size = params["batch_size"]

        num_examples = len(features)

        # This is for demo purposes and does NOT scale to large data sets. We do
        # not use Dataset.from_generator() because that uses tf.py_func which is
        # not TPU compatible. The right way to load data is with TFRecordReader.
        d = tf.data.Dataset.from_tensor_slices({
            "input_ids":
                tf.constant(
                    all_input_ids, shape=[num_examples, seq_length],
                    dtype=tf.int32),
            "input_mask":
                tf.constant(
                    all_input_mask,
                    shape=[num_examples, seq_length],
                    dtype=tf.int32),
            "segment_ids":
                tf.constant(
                    all_segment_ids,
                    shape=[num_examples, seq_length],
                    dtype=tf.int32),
            "label_ids":
                tf.constant(all_label_ids, shape=[num_examples], dtype=tf.int32),
        })

        if is_training:
            d = d.repeat()
            d = d.shuffle(buffer_size=100)

        d = d.batch(batch_size=batch_size, drop_remainder=drop_remainder)
        return d

    return input_fn


# This function is not used by this file but is still used by the Colab and
# people who depend on it.
def convert_examples_to_features(examples, label_list, max_seq_length,
                                 tokenizer):
    """Convert a set of `InputExample`s to a list of `InputFeatures`."""

    features = []
    for (ex_index, example) in enumerate(examples):
        if ex_index % 10000 == 0:
            tf.logging.info("Writing example %d of %d" % (ex_index, len(examples)))

        feature = convert_single_example(ex_index, example, label_list,
                                         max_seq_length, tokenizer)

        features.append(feature)
    return features


def main(_):
    tf.logging.set_verbosity(tf.logging.INFO)

    processors = {
        "adv": ADVProcessor,
    }

    tokenization.validate_case_matches_checkpoint(FLAGS.do_lower_case,
                                                  FLAGS.init_checkpoint)

    if not FLAGS.do_train and not FLAGS.do_eval and not FLAGS.do_predict:
        raise ValueError(
            "At least one of `do_train`, `do_eval` or `do_predict' must be True.")

    bert_config = modeling.BertConfig.from_json_file(FLAGS.bert_config_file)

    if FLAGS.max_seq_length > bert_config.max_position_embeddings:
        raise ValueError(
            "Cannot use sequence length %d because the BERT model "
            "was only trained up to sequence length %d" %
            (FLAGS.max_seq_length, bert_config.max_position_embeddings))

    tf.gfile.MakeDirs(FLAGS.output_dir)

    task_name = FLAGS.task_name.lower()

    if task_name not in processors:
        raise ValueError("Task not found: %s" % (task_name))

    processor = processors[task_name]()

    label_list = processor.get_labels()

    tokenizer = tokenization.FullTokenizer(
        vocab_file=FLAGS.vocab_file, do_lower_case=FLAGS.do_lower_case)

    tpu_cluster_resolver = None
    if FLAGS.use_tpu and FLAGS.tpu_name:
        tpu_cluster_resolver = tf.contrib.cluster_resolver.TPUClusterResolver(
            FLAGS.tpu_name, zone=FLAGS.tpu_zone, project=FLAGS.gcp_project)

    is_per_host = tf.contrib.tpu.InputPipelineConfig.PER_HOST_V2

    config = tf.ConfigProto()
    os.environ["CUDA_VISIBLE_DEVICES"] = "0"
    config.gpu_options.allow_growth = True
    config.allow_soft_placement = True
    config.log_device_placement = False
    config.gpu_options.per_process_gpu_memory_fraction = 0.9

    run_config = tf.contrib.tpu.RunConfig(
        cluster=tpu_cluster_resolver,
        master=FLAGS.master,
        model_dir=FLAGS.output_dir,
        save_checkpoints_steps=FLAGS.save_checkpoints_steps,
        session_config=config,
        keep_checkpoint_max=1,
        tpu_config=tf.contrib.tpu.TPUConfig(
            iterations_per_loop=FLAGS.iterations_per_loop,
            num_shards=FLAGS.num_tpu_cores,
            per_host_input_for_training=is_per_host))

    train_examples = None
    num_train_steps = None
    num_warmup_steps = None
    if FLAGS.do_train:
        train_examples = processor.get_train_examples(FLAGS.data_dir)
        num_train_steps = int(
            len(train_examples) / FLAGS.train_batch_size * FLAGS.num_train_epochs)
        num_warmup_steps = int(num_train_steps * FLAGS.warmup_proportion)

    model_fn = model_fn_builder(
        bert_config=bert_config,
        num_labels=len(label_list),
        init_checkpoint=FLAGS.init_checkpoint,
        learning_rate=FLAGS.learning_rate,
        num_train_steps=num_train_steps,
        num_warmup_steps=num_warmup_steps,
        use_tpu=FLAGS.use_tpu,
        use_one_hot_embeddings=FLAGS.use_tpu)

    # If TPU is not available, this will fall back to normal Estimator on CPU
    # or GPU.
    estimator = tf.contrib.tpu.TPUEstimator(
        use_tpu=FLAGS.use_tpu,
        model_fn=model_fn,
        config=run_config,
        train_batch_size=FLAGS.train_batch_size,
        eval_batch_size=FLAGS.eval_batch_size,
        predict_batch_size=FLAGS.predict_batch_size)



    # if FLAGS.do_train and FLAGS.do_eval:
    #     estimator =tf.estimator.Estimator(
    #         # use_tpu=FLAGS.use_tpu,
    #         model_fn=model_fn,
    #         config=run_config)
    #         # train_batch_size=FLAGS.train_batch_size,
    #         # eval_batch_size=FLAGS.eval_batch_size,
    #         # predict_batch_size=FLAGS.predict_batch_size)
    #
    #     train_file = os.path.join(FLAGS.output_dir, "train.tf_record")
    #     file_based_convert_examples_to_features(
    #         train_examples, label_list, FLAGS.max_seq_length, tokenizer, train_file)
    #
    #     eval_file = os.path.join(FLAGS.output_dir, "eval.tf_record")
    #     eval_examples = processor.get_dev_examples(FLAGS.data_dir)
    #     # num_actual_eval_examples = len(eval_examples)
    #     file_based_convert_examples_to_features(
    #         eval_examples, label_list, FLAGS.max_seq_length, tokenizer, eval_file)
    #     train_input_fn = file_based_input_fn_builder(
    #         input_file=train_file,
    #         seq_length=FLAGS.max_seq_length,
    #         is_training=True,
    #         drop_remainder=True)
    #
    #     train_spec = tf.estimator.TrainSpec(input_fn=train_input_fn, max_steps=1000)
    #     eval_drop_remainder = True if FLAGS.use_tpu else False
    #     eval_input_fn = file_based_input_fn_builder(
    #         input_file=eval_file,
    #         seq_length=FLAGS.max_seq_length,
    #         is_training=False,
    #         drop_remainder=eval_drop_remainder)
    #
    #     eval_spec = tf.estimator.EvalSpec(input_fn=eval_input_fn)
    #     estimator.train_and_evaluate(
    #         estimator,
    #         train_spec,
    #         eval_spec
    #     )

    if FLAGS.do_train:
        early_stop = tf.estimator.experimental.stop_if_no_decrease_hook(estimator, 'loss', 5)

        train_file = os.path.join(FLAGS.output_dir, "train.tf_record")
        file_based_convert_examples_to_features(
            train_examples, label_list, FLAGS.max_seq_length, tokenizer, train_file)
        tf.logging.info("***** Running training *****")
        tf.logging.info("  Num examples = %d", len(train_examples))
        tf.logging.info("  Batch size = %d", FLAGS.train_batch_size)
        tf.logging.info("  Num steps = %d", num_train_steps)
        train_input_fn = file_based_input_fn_builder(
            input_file=train_file,
            seq_length=FLAGS.max_seq_length,
            is_training=True,
            drop_remainder=True)
        estimator.train(input_fn=train_input_fn, max_steps=num_train_steps,hooks=[early_stop])

    if FLAGS.do_eval:
        eval_examples = processor.get_dev_examples(FLAGS.data_dir)
        num_actual_eval_examples = len(eval_examples)
        if FLAGS.use_tpu:
            # TPU requires a fixed batch size for all batches, therefore the number
            # of examples must be a multiple of the batch size, or else examples
            # will get dropped. So we pad with fake examples which are ignored
            # later on. These do NOT count towards the metric (all tf.metrics
            # support a per-instance weight, and these get a weight of 0.0).
            while len(eval_examples) % FLAGS.eval_batch_size != 0:
                eval_examples.append(PaddingInputExample())

        eval_file = os.path.join(FLAGS.output_dir, "eval" + str(random.randint(0, 100)) + ".tf_record")
        file_based_convert_examples_to_features(
            eval_examples, label_list, FLAGS.max_seq_length, tokenizer, eval_file)

        tf.logging.info("***** Running evaluation *****")
        tf.logging.info("  Num examples = %d (%d actual, %d padding)",
                        len(eval_examples), num_actual_eval_examples,
                        len(eval_examples) - num_actual_eval_examples)
        tf.logging.info("  Batch size = %d", FLAGS.eval_batch_size)

        # This tells the estimator to run through the entire set.
        eval_steps = None
        # However, if running eval on the TPU, you will need to specify the
        # number of steps.
        if FLAGS.use_tpu:
            assert len(eval_examples) % FLAGS.eval_batch_size == 0
            eval_steps = int(len(eval_examples) // FLAGS.eval_batch_size)

        eval_drop_remainder = True if FLAGS.use_tpu else False
        eval_input_fn = file_based_input_fn_builder(
            input_file=eval_file,
            seq_length=FLAGS.max_seq_length,
            is_training=False,
            drop_remainder=eval_drop_remainder)

        result = estimator.evaluate(input_fn=eval_input_fn, steps=eval_steps)

        output_eval_file = os.path.join(FLAGS.output_dir, "eval_results.txt")
        with tf.gfile.GFile(output_eval_file, "w") as writer:
            tf.logging.info("***** Eval results *****")
            for key in sorted(result.keys()):
                tf.logging.info("  %s = %s", key, str(result[key]))
                writer.write("%s = %s\n" % (key, str(result[key])))

    if FLAGS.do_predict:
        predict_examples = processor.get_dev_examples(FLAGS.data_dir)
        num_actual_predict_examples = len(predict_examples)
        if FLAGS.use_tpu:
            # TPU requires a fixed batch size for all batches, therefore the number
            # of examples must be a multiple of the batch size, or else examples
            # will get dropped. So we pad with fake examples which are ignored
            # later on.
            while len(predict_examples) % FLAGS.predict_batch_size != 0:
                predict_examples.append(PaddingInputExample())

        predict_file = os.path.join(FLAGS.output_dir, "predict" + str(random.randint(0, 1)) + ".tf_record")
        file_based_convert_examples_to_features(predict_examples, label_list,
                                                FLAGS.max_seq_length, tokenizer,
                                                predict_file)

        tf.logging.info("***** Running prediction*****")
        tf.logging.info("  Num examples = %d (%d actual, %d padding)",
                        len(predict_examples), num_actual_predict_examples,
                        len(predict_examples) - num_actual_predict_examples)
        tf.logging.info("  Batch size = %d", FLAGS.predict_batch_size)

        predict_drop_remainder = True if FLAGS.use_tpu else False
        predict_input_fn = file_based_input_fn_builder(
            input_file=predict_file,
            seq_length=FLAGS.max_seq_length,
            is_training=False,
            drop_remainder=predict_drop_remainder)

        result = estimator.predict(input_fn=predict_input_fn)

        output_predict_file = os.path.join(FLAGS.output_dir, "test_results.tsv")
        with tf.gfile.GFile(output_predict_file, "w") as writer:
            num_written_lines = 0
            tf.logging.info("***** Predict results *****")
            for (i, prediction) in enumerate(result):
                probabilities = prediction["probabilities"]
                if i >= num_actual_predict_examples:
                    break
                output_line = "\t".join(
                    str(round(class_probability))
                    for class_probability in probabilities)
                writer.write(
                    output_line + '\t' + str(predict_examples[i].label) + '\t' + predict_examples[i].text_a + "\n")
                num_written_lines += 1
        assert num_written_lines == num_actual_predict_examples


if __name__ == "__main__":
    flags.mark_flag_as_required("data_dir")
    flags.mark_flag_as_required("task_name")
    flags.mark_flag_as_required("vocab_file")
    flags.mark_flag_as_required("bert_config_file")
    flags.mark_flag_as_required("output_dir")
    tf.app.run()
