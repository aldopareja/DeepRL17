import os
import numpy as np
import tensorflow as tf


gradient_momentum = 0.95
squared_grad_mom = 0.95
min_sqr_grad = 0.01
summary_log_freq = 1000


class Learner:
    def __init__(self, name, sess, state_shape, action_n, batch_size, learning_rate, log_dir):
        raise NotImplementedError()

    def eval_batch(self, input_batch):
        return self.sess.run(self.output_tensor, feed_dict = {self.input_tensor:input_batch})
    
    def eval_batch_action(self, input_batch):
        return self.sess.run(self.best_action, feed_dict = {self.input_tensor:input_batch})

    def update_batch(self, input_batch, action_batch, target_batch):
        assert self.learning_rate is not None
        self.udpate_step += 1
        if self.udpate_step % summary_log_freq == 0:
            _, summary = self.sess.run([self.train_op, self.summary_op],
                        feed_dict = {self.input_tensor:input_batch,
                                    self.actions_tensor:action_batch,
                                    self.targets_tensor:target_batch})
            self.log_writer.add_summary(summary, global_step=self.udpate_step)
        else:
            self.sess.run(self.train_op,
                        feed_dict = {self.input_tensor:input_batch,
                                    self.actions_tensor:action_batch,
                                    self.targets_tensor:target_batch})
    
    def save(self, filePath):
        assert self.learning_rate is not None
        return self.saver.save(self.sess, filePath)
    
    def load(self, filePath):
        self.saver.restore(self.sess, filePath)
    
    def get_param(self):
        params =  self.sess.run(self.model_vars)
        return {t.name : v for t, v in zip(self.model_vars, params)}
    
    def set_param(self, param_map):
        feed_dict = {}
        for t, name in self.model_feed:
            feed_dict[t] = param_map[name]
        self.sess.run(self.assign_model_op, feed_dict=feed_dict)


class LinearLeaner(Learner):
    def __init__(self, name, sess, state_shape, action_n, batch_size, learning_rate, log_dir):
        self.state_shape = state_shape
        self.action_n = action_n
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.name = name
        self.sess = sess
        
        with tf.variable_scope(name):
            self.input_tensor = tf.placeholder(tf.float32, 
                                            shape = (batch_size,) + state_shape,
                                            name = 'input')
            with tf.variable_scope('model'):
                flattened_input = tf.reshape(self.input_tensor, (batch_size, -1), name='flatting') 
                self.output_tensor = tf.layers.dense(inputs = flattened_input,
                                              units = action_n,
                                              activation = None,
                                              kernel_initializer = tf.contrib.layers.xavier_initializer(),
                                              name = 'linear')
                self.best_action = tf.to_int32(tf.argmax(self.output_tensor, axis=1), name='best_action')
            
            self.model_vars = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope=name)
            with tf.name_scope('assign_model'):
                model_assign_ops = []
                self.model_feed = []
                for v in self.model_vars:
                    ph = tf.placeholder(v.dtype, shape=v.get_shape())
                    as_op = tf.assign(v, ph)
                    model_assign_ops.append(as_op)
                    self.model_feed.append((ph, v.name))
                self.assign_model_op = tf.group(*model_assign_ops, name='assign_model')
            
            if learning_rate is not None:
                self.actions_tensor = tf.placeholder(tf.int32,
                                                    shape = batch_size,
                                                    name = 'actions')
                self.targets_tensor = tf.placeholder(tf.float32,
                                                    shape = batch_size,
                                                    name = 'targets')
                with tf.variable_scope('loss'):
                    act_one_hot = tf.one_hot(indices = self.actions_tensor,
                                                    depth = action_n,
                                                    on_value = 1.0,
                                                    off_value = 0.0,
                                                    name = 'act_one_hot')
                    self.q_pred = tf.reduce_sum(self.output_tensor * act_one_hot,
                                                reduction_indices = 1,
                                                name = 'q_pred')
                    self.diff = self.q_pred - self.targets_tensor
                    err = tf.abs(self.diff)
                    self.hub_loss = tf.where(condition = err < 1.0,
                                                x = 0.5 * tf.square(self.diff),
                                                y = err - 0.5,
                                                name = 'huber_loss')

                with tf.variable_scope('optim'):
                    self.total_loss = tf.reduce_mean(self.hub_loss, name = 'total_loss')
                    self.train_op = tf.train.RMSPropOptimizer(learning_rate=self.learning_rate, momentum=gradient_momentum, \
                                                              decay=squared_grad_mom, epsilon=min_sqr_grad)\
                                            .minimize(self.total_loss, var_list=tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope=name))

                with tf.name_scope('endpoints'):
                    tf.summary.histogram('input', self.input_tensor)
                    tf.summary.histogram('output', self.output_tensor)
                    tf.summary.histogram('actions', self.actions_tensor)
                    tf.summary.histogram('targets', self.targets_tensor)
                    tf.summary.histogram('Q_pred', self.q_pred)
                    tf.summary.histogram('Q_diff', self.diff)
                    tf.summary.histogram('huber_loss', self.hub_loss)
                    tf.summary.scalar('total_loss', self.total_loss)

                with tf.name_scope('parameters'):
                    for param in tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope=name):
                        tf.summary.histogram(param.name, param)

                self.summary_op = tf.summary.merge(tf.get_collection(tf.GraphKeys.SUMMARIES, scope=name))
                assert log_dir is not None
                if not os.path.exists(log_dir):
                    os.makedirs(log_dir)
                self.log_writer = tf.summary.FileWriter(log_dir, graph=self.sess.graph)

            init_op = tf.variables_initializer(tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope=name))
            self.sess.run(init_op)

            self.saver = tf.train.Saver(var_list=tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope=name),
                                        max_to_keep=1000)

            self.udpate_step = 0


class DeepLearner(Learner):
    def __init__(self, name, sess, state_shape, action_n, batch_size, learning_rate, log_dir):
        self.state_shape = state_shape
        self.action_n = action_n
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.name = name
        self.sess = sess
        
        with tf.variable_scope(name):
            self.input_tensor = tf.placeholder(tf.float32,
                                            shape = (batch_size,) + state_shape,
                                            name = 'input')
            self.channels_last = tf.transpose(self.input_tensor,perm=[0,2,3,1])
            with tf.variable_scope('model'):
                with tf.variable_scope('conv_layers'):
                    self.conv1 = tf.layers.conv2d(inputs = self.channels_last,
                                                filters = 16,
                                                kernel_size= (8,8),
                                                strides = (4,4),
                                                #must change so that it works on CPU
                                                #data_format = 'channels_first',
                                                kernel_initializer = tf.contrib.layers.xavier_initializer(),
                                                bias_initializer = tf.constant_initializer(),
                                                activation = tf.nn.relu,
                                                name = 'conv1')
                    self.conv2 = tf.layers.conv2d(inputs = self.conv1,
                                                filters = 32,
                                                kernel_size= (4,4),
                                                strides = (2,2),
                                                #data_format = 'channels_first',
                                                kernel_initializer = tf.contrib.layers.xavier_initializer(),
                                                bias_initializer = tf.constant_initializer(),
                                                activation = tf.nn.relu,
                                                name = 'conv2')
                with tf.variable_scope('dense_layers'):
                    flattened_tensor = tf.reshape(self.conv2,(batch_size,-1),name='flatting') 
                    self.fcl1 = tf.layers.dense(inputs = flattened_tensor,
                                            units = 256,
                                            activation = tf.nn.relu,
                                            kernel_initializer = tf.contrib.layers.xavier_initializer(),
                                            bias_initializer = tf.constant_initializer(),
                                            name = 'fcl1')
                    self.output_tensor = tf.layers.dense(inputs = self.fcl1,
                                            units = action_n,
                                            activation = None,
                                            kernel_initializer = tf.contrib.layers.xavier_initializer(),
                                            bias_initializer = tf.constant_initializer(),
                                            name = 'linear')
                self.best_action = tf.to_int32(tf.argmax(self.output_tensor, axis=1), name='best_action')
            
            self.model_vars = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope=name)
            with tf.name_scope('assign_model'):
                model_assign_ops = []
                self.model_feed = []
                for v in self.model_vars:
                    ph = tf.placeholder(v.dtype, shape=v.get_shape())
                    as_op = tf.assign(v, ph)
                    model_assign_ops.append(as_op)
                    self.model_feed.append((ph, v.name))
                self.assign_model_op = tf.group(*model_assign_ops, name='assign_model')
            
            if learning_rate is not None:
                self.actions_tensor = tf.placeholder(tf.int32,
                                                    shape = batch_size,
                                                    name = 'actions')
                self.targets_tensor = tf.placeholder(tf.float32,
                                                    shape = batch_size,
                                                    name = 'targets')
                with tf.variable_scope('loss'):
                    act_one_hot = tf.one_hot(indices = self.actions_tensor,
                                                    depth = action_n,
                                                    on_value = 1.0,
                                                    off_value = 0.0,
                                                    name = 'act_one_hot')
                    self.q_pred = tf.reduce_sum(self.output_tensor * act_one_hot,
                                                reduction_indices = 1,
                                                name = 'q_pred')
                    self.diff = self.q_pred - self.targets_tensor
                    err = tf.abs(self.diff)
                    self.hub_loss = tf.where(condition = err < 1.0,
                                                x = 0.5 * tf.square(self.diff),
                                                y = err - 0.5,
                                                name = 'huber_loss')

                with tf.variable_scope('optim'):
                    self.total_loss = tf.reduce_mean(self.hub_loss, name = 'total_loss')
                    self.train_op = tf.train.RMSPropOptimizer(learning_rate=self.learning_rate, momentum=gradient_momentum, \
                                                              decay=squared_grad_mom, epsilon=min_sqr_grad)\
                                            .minimize(self.total_loss, var_list=tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope=name))

                with tf.name_scope('endpoints'):
                    tf.summary.histogram('input', self.input_tensor)
                    tf.summary.histogram('conv1', self.conv1)
                    tf.summary.histogram('conv2', self.conv2)
                    tf.summary.histogram('fcl1', self.fcl1)
                    tf.summary.histogram('output', self.output_tensor)
                    tf.summary.histogram('actions', self.actions_tensor)
                    tf.summary.histogram('targets', self.targets_tensor)
                    tf.summary.histogram('Q_pred', self.q_pred)
                    tf.summary.histogram('Q_diff', self.diff)
                    tf.summary.histogram('huber_loss', self.hub_loss)
                    tf.summary.scalar('total_loss', self.total_loss)

                with tf.name_scope('parameters'):
                    for param in tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope=name):
                        tf.summary.histogram(param.name, param)

                self.summary_op = tf.summary.merge(tf.get_collection(tf.GraphKeys.SUMMARIES, scope=name))
                assert log_dir is not None
                if not os.path.exists(log_dir):
                    os.makedirs(log_dir)
                self.log_writer = tf.summary.FileWriter(log_dir, graph=self.sess.graph)

            init_op = tf.variables_initializer(tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope=name))
            self.sess.run(init_op)

            self.saver = tf.train.Saver(var_list=tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope=name),
                                        max_to_keep=1000)

            self.udpate_step = 0


class DeepDuelLearner(Learner):
    def __init__(self, name, sess, state_shape, action_n, batch_size, learning_rate, log_dir):
        self.state_shape = state_shape
        self.action_n = action_n
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.name = name
        self.sess = sess
        
        with tf.variable_scope(name):
            self.input_tensor = tf.placeholder(tf.float32, 
                                            shape = (batch_size,) + state_shape,
                                            name = 'input')
            with tf.variable_scope('model'):
                with tf.variable_scope('value_net'):
                    with tf.variable_scope('conv_layers'):
                        self.value_conv1 = tf.layers.conv2d(inputs = self.input_tensor,
                                                    filters = 16,
                                                    kernel_size= (8,8),
                                                    strides = (4,4),
                                                    data_format = 'channels_first',
                                                    kernel_initializer = tf.contrib.layers.xavier_initializer(),
                                                    bias_initializer = tf.constant_initializer(),
                                                    activation = tf.nn.relu,
                                                    name = 'conv1')
                        self.value_conv2 = tf.layers.conv2d(inputs = self.value_conv1,
                                                    filters = 32,
                                                    kernel_size= (4,4),
                                                    strides = (2,2),
                                                    data_format = 'channels_first',
                                                    kernel_initializer = tf.contrib.layers.xavier_initializer(),
                                                    bias_initializer = tf.constant_initializer(),
                                                    activation = tf.nn.relu,
                                                    name = 'conv2')
                    with tf.variable_scope('dense_layers'):
                        flattened_tensor = tf.reshape(self.value_conv2,(batch_size,-1),name='flatting') 
                        self.value_fcl1 = tf.layers.dense(inputs = flattened_tensor,
                                                units = 256,
                                                activation = tf.nn.relu,
                                                kernel_initializer = tf.contrib.layers.xavier_initializer(),
                                                bias_initializer = tf.constant_initializer(),
                                                name = 'fcl1')
                        self.value_output = tf.layers.dense(inputs = self.value_fcl1,
                                                units = 1,
                                                activation = None,
                                                kernel_initializer = tf.contrib.layers.xavier_initializer(),
                                                bias_initializer = tf.constant_initializer(),
                                                name = 'linear')

                with tf.variable_scope('action_net'):
                    with tf.variable_scope('conv_layers'):
                        self.action_conv1 = tf.layers.conv2d(inputs = self.input_tensor,
                                                    filters = 16,
                                                    kernel_size= (8,8),
                                                    strides = (4,4),
                                                    data_format = 'channels_first',
                                                    kernel_initializer = tf.contrib.layers.xavier_initializer(),
                                                    bias_initializer = tf.constant_initializer(),
                                                    activation = tf.nn.relu,
                                                    name = 'conv1')
                        self.action_conv2 = tf.layers.conv2d(inputs = self.action_conv1,
                                                    filters = 32,
                                                    kernel_size= (4,4),
                                                    strides = (2,2),
                                                    data_format = 'channels_first',
                                                    kernel_initializer = tf.contrib.layers.xavier_initializer(),
                                                    bias_initializer = tf.constant_initializer(),
                                                    activation = tf.nn.relu,
                                                    name = 'conv2')
                    with tf.variable_scope('dense_layers'):
                        flattened_tensor = tf.reshape(self.action_conv2,(batch_size,-1),name='flatting') 
                        self.action_fcl1 = tf.layers.dense(inputs = flattened_tensor,
                                                units = 256,
                                                activation = tf.nn.relu,
                                                kernel_initializer = tf.contrib.layers.xavier_initializer(),
                                                bias_initializer = tf.constant_initializer(),
                                                name = 'fcl1')
                        self.action_output = tf.layers.dense(inputs = self.action_fcl1,
                                                units = action_n,
                                                activation = None,
                                                kernel_initializer = tf.contrib.layers.xavier_initializer(),
                                                bias_initializer = tf.constant_initializer(),
                                                name = 'linear')

                self.output_tensor = tf.add(self.action_output, tf.subtract(self.value_output, \
                                            tf.reduce_mean(self.action_output, axis=1, keep_dims=True)), name='output')
                self.best_action = tf.to_int32(tf.argmax(self.output_tensor, axis=1), name='best_action')
            
            self.model_vars = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope=name)
            with tf.name_scope('assign_model'):
                model_assign_ops = []
                self.model_feed = []
                for v in self.model_vars:
                    ph = tf.placeholder(v.dtype, shape=v.get_shape())
                    as_op = tf.assign(v, ph)
                    model_assign_ops.append(as_op)
                    self.model_feed.append((ph, v.name))
                self.assign_model_op = tf.group(*model_assign_ops, name='assign_model')

            if learning_rate is not None:
                self.actions_tensor = tf.placeholder(tf.int32,
                                                    shape = batch_size,
                                                    name = 'actions')
                self.targets_tensor = tf.placeholder(tf.float32,
                                                    shape = batch_size,
                                                    name = 'targets')
                with tf.variable_scope('loss'):
                    act_one_hot = tf.one_hot(indices = self.actions_tensor,
                                                    depth = action_n,
                                                    on_value = 1.0,
                                                    off_value = 0.0,
                                                    name = 'act_one_hot')
                    self.q_pred = tf.reduce_sum(self.output_tensor * act_one_hot,
                                                reduction_indices = 1,
                                                name = 'q_pred')
                    self.diff = self.q_pred - self.targets_tensor
                    err = tf.abs(self.diff)
                    self.hub_loss = tf.where(condition = err < 1.0,
                                                x = 0.5 * tf.square(self.diff),
                                                y = err - 0.5,
                                                name = 'huber_loss')

                with tf.variable_scope('optim'):
                    self.total_loss = tf.reduce_mean(self.hub_loss, name = 'total_loss')
                    self.train_op = tf.train.RMSPropOptimizer(learning_rate=self.learning_rate, momentum=gradient_momentum, \
                                                              decay=squared_grad_mom, epsilon=min_sqr_grad)\
                                            .minimize(self.total_loss, var_list=tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope=name))

                with tf.name_scope('endpoints'):
                    tf.summary.histogram('input', self.input_tensor)
                    with tf.name_scope('value_net'):
                        tf.summary.histogram('conv1', self.value_conv1)
                        tf.summary.histogram('conv2', self.value_conv2)
                        tf.summary.histogram('fcl1', self.value_fcl1)
                        tf.summary.histogram('output', self.value_output)
                    with tf.name_scope('action_net'):
                        tf.summary.histogram('conv1', self.action_conv1)
                        tf.summary.histogram('conv2', self.action_conv2)
                        tf.summary.histogram('fcl1', self.action_fcl1)
                        tf.summary.histogram('output', self.action_output)
                    tf.summary.histogram('output', self.output_tensor)
                    tf.summary.histogram('actions', self.actions_tensor)
                    tf.summary.histogram('targets', self.targets_tensor)
                    tf.summary.histogram('Q_pred', self.q_pred)
                    tf.summary.histogram('Q_diff', self.diff)
                    tf.summary.histogram('huber_loss', self.hub_loss)
                    tf.summary.scalar('total_loss', self.total_loss)

                with tf.name_scope('parameters'):
                    for param in tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope=name):
                        tf.summary.histogram(param.name, param)

                self.summary_op = tf.summary.merge(tf.get_collection(tf.GraphKeys.SUMMARIES, scope=name))
                assert log_dir is not None
                if not os.path.exists(log_dir):
                    os.makedirs(log_dir)
                self.log_writer = tf.summary.FileWriter(log_dir, graph=self.sess.graph)

            init_op = tf.variables_initializer(tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope=name))
            self.sess.run(init_op)

            self.saver = tf.train.Saver(var_list=tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope=name),
                                        max_to_keep=1000)

            self.udpate_step = 0
