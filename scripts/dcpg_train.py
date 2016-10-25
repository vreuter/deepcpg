#!/usr/bin/env python

from collections import OrderedDict
import os
import random
import re
import sys

import argparse
import logging
import numpy as np
import pandas as pd

from keras import backend as K
from keras import callbacks as kcbk
from keras.models import Model
from keras.optimizers import Adam

from deepcpg import callbacks as cbk
from deepcpg import data as dat
from deepcpg import metrics as met
from deepcpg import models as mod
from deepcpg.utils import format_table, EPS


LOG_PRECISION = 4


def get_output_weights(output_names, weight_patterns):
    regex_weights = dict()
    for weight_pattern in weight_patterns:
        tmp = [tmp.strip() for tmp in weight_pattern.split('=')]
        if len(tmp) != 2:
            raise ValueError('Invalid weight pattern "%s"!' % (weight_pattern))
        regex_weights[tmp[0]] = float(tmp[1])

    output_weights = dict()
    for output_name in output_names:
        for regex, weight in regex_weights.items():
            if re.match(regex, output_name):
                output_weights[output_name] = weight
        if output_name not in output_weights:
            output_weights[output_name] = 1.0
    return output_weights


def get_class_weight(output_name, output_stats):
    if output_name.startswith('cpg'):
        frac_one = max(output_stats['mean'], EPS)
        weight = OrderedDict()
        weight[0] = frac_one
        weight[1] = 1 - frac_one
    else:
        weight = None
    return weight


def perf_logs_str(logs):
    t = logs.to_csv(None, sep='\t', float_format='%.4f', index=False)
    return t


def get_objectives(output_names):
    objectives = dict()
    for output_name in output_names:
        if output_name.startswith('cpg'):
            objective = 'binary_crossentropy'
        elif output_name == 'stats/diff':
            objective = 'binary_crossentropy'
        elif output_name in ['stats/mean', 'stats/var']:
            objective = 'mean_squared_error'
        else:
            raise ValueError('Invalid output name "%s"!')
        objectives[output_name] = objective
    return objectives


def get_metrics(output_name):
    if output_name.startswith('cpg') or output_name == 'stats/diff':
        metrics = [met.acc, met.tpr, met.tnr, met.f1, met.mcc]
    elif output_name in ['stats/mean', 'stats/var']:
        metrics = [met.mse, met.mae]
    else:
        raise ValueError('Invalid output name "%s"!' % output_name)
    return metrics


class App(object):

    def run(self, args):
        name = os.path.basename(args[0])
        parser = self.create_parser(name)
        opts = parser.parse_args(args[1:])
        return self.main(name, opts)

    def create_parser(self, name):
        p = argparse.ArgumentParser(
            prog=name,
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
            description='Train model')
        p.add_argument(
            'train_files',
            nargs='+',
            help='Training data files')
        p.add_argument(
            '--val_files',
            nargs='+',
            help='Validation data files')
        p.add_argument(
            '-o', '--out_dir',
            default='./train',
            help='Output directory')
        p.add_argument(
            '--output_names',
            help='List of regex to filter outputs',
            nargs='+',
            default=['cpg/.*'])
        p.add_argument(
            '--output_weights',
            help='List of regex=weight patterns',
            nargs='+')
        p.add_argument(
            '--nb_output',
            type=int,
            help='Maximum number of outputs')
        p.add_argument(
            '--replicate_names',
            help='List of regex to filter CpG context units',
            nargs='+')
        p.add_argument(
            '--nb_replicate',
            type=int,
            help='Maximum number of replicates')
        p.add_argument(
            '--model_name',
            help='Model name',
            default='dna01')
        p.add_argument(
            '--nb_epoch',
            help='Maximum # training epochs',
            type=int,
            default=100)
        p.add_argument(
            '--batch_size',
            help='Batch size',
            type=int,
            default=128)
        p.add_argument(
            '--early_stopping',
            help='Early stopping patience',
            type=int,
            default=3)
        p.add_argument(
            '--learning_rate',
            help='Learning rate',
            type=float,
            default=0.0001)
        p.add_argument(
            '--learning_rate_decay',
            help='Exponential learning rate decay factor',
            type=float,
            default=0.975)
        p.add_argument(
            '--nb_train_sample',
            help='Maximum # training samples',
            type=int)
        p.add_argument(
            '--nb_val_sample',
            help='Maximum # validation samples',
            type=int)
        p.add_argument(
            '--max_time',
            help='Maximum training time in hours',
            type=float)
        p.add_argument(
            '--stop_file',
            help='Stop training if this file exists')
        p.add_argument(
            '--no_class_weights',
            help='Do not weight classes',
            action='store_true')
        p.add_argument(
            '--seed',
            help='Seed of rng',
            type=int,
            default=0)
        p.add_argument(
            '--no_log_outputs',
            help='Do not log performance metrics of individual outputs',
            action='store_true')
        p.add_argument(
            '--verbose',
            help='More detailed log messages',
            action='store_true')
        p.add_argument(
            '--log_file',
            help='Write log messages to file')
        p.add_argument(
            '--dna_wlen',
            help='DNA window length',
            type=int)
        p.add_argument(
            '--cpg_wlen',
            help='CpG window length',
            type=int)
        p.add_argument(
            '--dropout',
            help='Dropout rate',
            type=float,
            default=0.0)
        p.add_argument(
            '--l1_decay',
            help='L1 weight decay',
            type=float,
            default=0.0)
        p.add_argument(
            '--l2_decay',
            help='L2 weight decay',
            type=float,
            default=0.0)
        p.add_argument(
            '--initialization',
            help='Parameter initialization',
            default='he_uniform')
        p.add_argument(
            '--data_q_size',
            help='Size of data generator queue',
            type=int,
            default=10)
        p.add_argument(
            '--data_nb_worker',
            help='Number of worker for data generator queue',
            type=int,
            default=1)
        return p

    def callbacks(self):
        opts = self.opts
        cbacks = []

        if opts.val_files:
            cbacks.append(kcbk.EarlyStopping(
                'val_loss' if opts.val_files else 'loss',
                patience=opts.early_stopping,
                verbose=1
            ))

        cbacks.append(kcbk.ModelCheckpoint(
            os.path.join(opts.out_dir, 'model_weights_last.h5'),
            save_best_only=False))
        monitor = 'val_loss' if opts.val_files else 'loss'
        cbacks.append(kcbk.ModelCheckpoint(
            os.path.join(opts.out_dir, 'model_weights.h5'),
            monitor=monitor,
            save_best_only=True, verbose=1
        ))

        max_time = int(opts.max_time * 3600) if opts.max_time else None
        cbacks.append(cbk.TrainingStopper(
            max_time=max_time,
            stop_file=opts.stop_file,
            verbose=1
        ))

        def learning_rate_schedule(epoch):
            lr = opts.learning_rate * opts.learning_rate_decay**epoch
            print('Learning rate: %.3g' % lr)
            return lr

        cbacks.append(kcbk.LearningRateScheduler(learning_rate_schedule))

        def save_lc(epoch, epoch_logs, val_epoch_logs):
            logs = {'lc_train.csv': epoch_logs,
                    'lc_val.csv': val_epoch_logs}
            for name, logs in logs.items():
                if not logs:
                    continue
                logs = pd.DataFrame(logs)
                with open(os.path.join(opts.out_dir, name), 'w') as f:
                    f.write(perf_logs_str(logs))

        metrics = OrderedDict()
        for metric_funs in self.metrics.values():
            for metric_fun in metric_funs:
                metrics[metric_fun.__name__] = True
        metrics = ['loss'] + list(metrics.keys())

        self.perf_logger = cbk.PerformanceLogger(
            callbacks=[save_lc],
            metrics=metrics,
            precision=LOG_PRECISION,
            verbose=not opts.no_log_outputs
        )
        cbacks.append(self.perf_logger)

        if K._BACKEND == 'tensorflow':
            cbacks.append(cbk.TensorBoard(
                log_dir=opts.out_dir,
                histogram_freq=1,
                write_graph=True,
                write_images=True
            ))

        return cbacks

    def main(self, name, opts):
        logging.basicConfig(filename=opts.log_file,
                            format='%(levelname)s (%(asctime)s): %(message)s')
        log = logging.getLogger(name)
        if opts.verbose:
            log.setLevel(logging.DEBUG)
        else:
            log.setLevel(logging.INFO)

        if opts.seed is not None:
            np.random.seed(opts.seed)
            random.seed(opts.seed)

        self.log = log
        self.opts = opts

        # Create output directory if not existing
        if not os.path.exists(opts.out_dir):
            os.makedirs(opts.out_dir, exist_ok=True)

        log.info('Computing output statistics ...')
        output_names = dat.get_output_names(opts.train_files[0],
                                            regex=opts.output_names,
                                            nb_keys=opts.nb_output)
        if not output_names:
            raise ValueError('No outputs found!')
        print(output_names)
        output_stats = dat.get_output_stats(opts.train_files, output_names)

        table = OrderedDict()
        for name, stat in output_stats.items():
            table.setdefault('name', []).append(name)
            for key in ['nb_tot', 'frac_obs', 'mean', 'var']:
                table.setdefault(key, []).append(stat[key])
        print('Output statistics:')
        print(format_table(table))
        print()

        class_weights = None
        if not opts.no_class_weights:
            log.info('Initializing class weights ...')
            class_weights = OrderedDict()
            for output_name in output_names:
                class_weights[output_name] = get_class_weight(
                    output_name, output_stats[output_name])

            table = OrderedDict()
            for output_name in output_names:
                class_weight = class_weights[output_name]
                if not class_weight:
                    continue
                column = []
                for cla, weight in class_weight.items():
                    column.append('%s=%.2f' % (cla, weight))
                table[output_name] = column

            if table:
                print('Class weights:')
                print(format_table(table))
                print()

        output_weights = None
        if opts.output_weights:
            log.info('Initializing output weights ...')
            output_weights = get_output_weights(output_names,
                                                opts.output_weights)
            print('Output weights:')
            for output_name in output_names:
                if output_name in output_weights:
                    print('%s: %.2f' % (output_name,
                                        output_weights[output_name]))
            print()

        log.info('Building model ...')
        model_builder = mod.get_class(opts.model_name)

        _model_name = opts.model_name.lower()

        if _model_name.startswith('dna') or _model_name.startswith('joint'):
            dna_wlen = dat.get_dna_wlen(opts.train_files[0], opts.dna_wlen)

        if _model_name.startswith('cpg') or _model_name.startswith('joint'):
            cpg_wlen = dat.get_cpg_wlen(opts.train_files[0], opts.cpg_wlen)
            replicate_names = dat.get_replicate_names(
                opts.train_files[0],
                regex=opts.replicate_names,
                nb_keys=opts.nb_replicate)
            if not replicate_names:
                raise ValueError('Not replicates found!')
            print('Replicate names:')
            for replicate_name in replicate_names:
                print(replicate_name)
            print()

        if _model_name.startswith('dna'):
            model_builder = model_builder(dna_wlen=dna_wlen,
                                          dropout=opts.dropout,
                                          l1_decay=opts.l1_decay,
                                          l2_decay=opts.l2_decay,
                                          init=opts.initialization)
        elif _model_name.startswith('cpg'):
            model_builder = model_builder(replicate_names,
                                          cpg_wlen=cpg_wlen,
                                          dropout=opts.dropout,
                                          l1_decay=opts.l1_decay,
                                          l2_decay=opts.l2_decay,
                                          init=opts.initialization)
        else:
            model_builder = model_builder(replicate_names=replicate_names,
                                          cpg_wlen=cpg_wlen,
                                          dna_wlen=dna_wlen,
                                          dropout=opts.dropout,
                                          l1_decay=opts.l1_decay,
                                          l2_decay=opts.l2_decay,
                                          init=opts.initialization)

        inputs = model_builder.inputs()
        stem = model_builder(inputs)
        outputs = mod.add_output_layers(stem, output_names)
        model = Model(input=inputs, output=outputs, name=opts.model_name)
        model.summary()

        mod.save_model(model, os.path.join(opts.out_dir, 'model.json'))

        log.info('Compile model ...')

        self.metrics = dict()
        for output_name in output_names:
            self.metrics[output_name] = get_metrics(output_name)

        optimizer = Adam(lr=opts.learning_rate)
        model.compile(optimizer=optimizer,
                      loss=get_objectives(output_names),
                      loss_weights=output_weights,
                      metrics=self.metrics)

        log.info('Initializing callbacks ...')
        cbacks = self.callbacks()

        log.info('Reading data ...')
        nb_train_sample = dat.get_nb_sample(opts.train_files,
                                            opts.nb_train_sample)
        if not nb_train_sample:
            raise ValueError('Two few training samples!')
        train_data = model_builder.reader(opts.train_files,
                                          output_names=output_names,
                                          batch_size=opts.batch_size,
                                          nb_sample=nb_train_sample,
                                          loop=True, shuffle=True,
                                          class_weights=class_weights)
        if opts.val_files:
            nb_val_sample = dat.get_nb_sample(opts.val_files,
                                              opts.nb_val_sample)
            if not nb_val_sample:
                raise ValueError('Two few validation samples!')
            val_data = model_builder.reader(opts.val_files,
                                            output_names=output_names,
                                            batch_size=opts.batch_size,
                                            nb_sample=nb_val_sample,
                                            loop=True, shuffle=False,
                                            class_weights=class_weights)
        else:
            val_data = None
            nb_val_sample = None

        # Train model
        log.info('Training model ...')
        print()
        model.fit_generator(
            train_data, nb_train_sample, opts.nb_epoch,
            callbacks=cbacks,
            validation_data=val_data,
            nb_val_samples=nb_val_sample,
            max_q_size=opts.data_q_size,
            nb_worker=opts.data_nb_worker,
            verbose=0)

        print('\nTraining set performance:')
        print(format_table(self.perf_logger.epoch_logs,
                           precision=LOG_PRECISION))

        if self.perf_logger.val_epoch_logs:
            print('\nValidation set performance:')
            print(format_table(self.perf_logger.val_epoch_logs,
                               precision=LOG_PRECISION))

        # Restore model with highest validation performance
        filename = os.path.join(opts.out_dir, 'model_weights.h5')
        if os.path.isfile(filename):
            model.load_weights(filename)

        # Delete metrics since they cause problems when loading the model
        # from HDF5 file
        model.metrics = None
        model.metrics_names = None
        model.metrics_tensors = None
        model.save(os.path.join(opts.out_dir, 'model.h5'))

        log.info('Done!')

        return 0


if __name__ == '__main__':
    app = App()
    app.run(sys.argv)