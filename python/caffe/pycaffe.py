"""
Wrap the internal caffe C++ module (_caffe.so) with a clean, Pythonic
interface.
"""

from collections import OrderedDict
from itertools import izip_longest
import numpy as np
from scipy.ndimage import zoom

from ._caffe import Net, SGDSolver

# We directly update methods from Net here (rather than using composition or
# inheritance) so that nets created by caffe (e.g., by SGDSolver) will
# automatically have the improved interface.

# Input preprocessing
Net.mean = {}       # image mean (ndarray, input dimensional or broadcastable)
Net.input_scale = {}    # for a model that expects data = input * input_scale
Net.channel_swap = {}  # for RGB -> BGR and the like


@property
def _Net_blobs(self):
    """
    An OrderedDict (bottom to top, i.e., input to output) of network
    blobs indexed by name
    """
    return OrderedDict([(bl.name, bl) for bl in self._blobs])


@property
def _Net_params(self):
    """
    An OrderedDict (bottom to top, i.e., input to output) of network
    parameters indexed by name; each is a list of multiple blobs (e.g.,
    weights and biases)
    """
    return OrderedDict([(lr.name, lr.blobs) for lr in self.layers
                        if len(lr.blobs) > 0])


def _Net_forward(self, blobs=None, **kwargs):
    """
    Forward pass: prepare inputs and run the net forward.

    Take
    blobs: list of blobs to return in addition to output blobs.
    kwargs: Keys are input blob names and values are blob ndarrays.
            For turning images into input blobs, see caffeinate()().
            If None, input is taken from data layers.

    Give
    outs: {blob name: blob ndarray} dict.
    """
    if blobs is None:
        blobs = []

    if kwargs:
        if set(kwargs.keys()) != set(self.inputs):
            raise Exception('Input blob arguments do not match net inputs.')
        # Set input according to defined shapes and make arrays single and
        # C-contiguous as Caffe expects.
        for in_, blob in kwargs.iteritems():
            if blob.shape[0] != self.blobs[in_].num:
                raise Exception('Input is not batch sized')
            if blob.ndim != 4:
                raise Exception('{} blob is not 4-d'.format(in_))
            self.blobs[in_].data[...] = blob

    self._forward()

    # Unpack blobs to extract
    outs = {out: self.blobs[out].data for out in set(self.outputs + blobs)}
    return outs


def _Net_backward(self, diffs=None, **kwargs):
    """
    Backward pass: prepare diffs and run the net backward.

    Take
    diffs: list of diffs to return in addition to bottom diffs.
    kwargs: Keys are output blob names and values are diff ndarrays.
            If None, top diffs are taken from forward loss.

    Give
    outs: {blob name: diff ndarray} dict.
    """
    if diffs is None:
        diffs = []

    if kwargs:
        if set(kwargs.keys()) != set(self.outputs):
            raise Exception('Top diff arguments do not match net outputs.')
        # Set top diffs according to defined shapes and make arrays single and
        # C-contiguous as Caffe expects.
        for top, diff in kwargs.iteritems():
            if diff.shape[0] != self.blobs[top].num:
                raise Exception('Diff is not batch sized')
            if diff.ndim != 4:
                raise Exception('{} diff is not 4-d'.format(top))
            self.blobs[top].diff[...] = diff

    self._backward()

    # Unpack diffs to extract
    outs = {out: self.blobs[out].diff for out in set(self.inputs + diffs)}
    return outs


def _Net_forward_all(self, blobs=None, **kwargs):
    """
    Run net forward in batches.

    Take
    blobs: list of blobs to extract as in forward()
    kwargs: Keys are input blob names and values are blob ndarrays.
            Refer to forward().

    Give
    all_outs: {blob name: list of blobs} dict.
    """
    # Collect outputs from batches
    all_outs = {out: [] for out in set(self.outputs + (blobs or []))}
    for batch in self._batch(kwargs):
        outs = self.forward(blobs=blobs, **batch)
        for out, out_blob in outs.iteritems():
            all_outs[out].extend(out_blob)
    # Package in ndarray.
    for out in all_outs:
        all_outs[out] = np.asarray(all_outs[out])
    # Discard padding.
    pad = len(all_outs.itervalues().next()) - len(kwargs.itervalues().next())
    if pad:
        for out in all_outs:
            all_outs[out] = all_outs[out][:-pad]
    return all_outs


def _Net_forward_backward_all(self, blobs=None, diffs=None, **kwargs):
    """
    Run net forward + backward in batches.

    Take
    blobs: list of blobs to extract as in forward()
    diffs: list of diffs to extract as in backward()
    kwargs: Keys are input (for forward) and output (for backward) blob names
            and values are ndarrays. Refer to forward() and backward().
            Prefilled variants are called for lack of input or output blobs.

    Give
    all_blobs: {blob name: blob ndarray} dict.
    all_diffs: {blob name: diff ndarray} dict.
    """
    # Batch blobs and diffs.
    all_outs = {out: [] for out in set(self.outputs + (blobs or []))}
    all_diffs = {diff: [] for diff in set(self.inputs + (diffs or []))}
    forward_batches = self._batch({in_: kwargs[in_]
                                   for in_ in self.inputs if in_ in kwargs})
    backward_batches = self._batch({out: kwargs[out]
                                    for out in self.outputs if out in kwargs})
    # Collect outputs from batches (and heed lack of forward/backward batches).
    for fb, bb in izip_longest(forward_batches, backward_batches, fillvalue={}):
        batch_blobs = self.forward(blobs=blobs, **fb)
        batch_diffs = self.backward(diffs=diffs, **bb)
        for out, out_blobs in batch_blobs.iteritems():
            all_outs[out].extend(out_blobs)
        for diff, out_diffs in batch_diffs.iteritems():
            all_diffs[diff].extend(out_diffs)
    # Package in ndarray.
    for out, diff in zip(all_outs, all_diffs):
        all_outs[out] = np.asarray(all_outs[out])
        all_diffs[diff] = np.asarray(all_diffs[diff])
    # Discard padding at the end and package in ndarray.
    pad = len(all_outs.itervalues().next()) - len(kwargs.itervalues().next())
    if pad:
        for out, diff in zip(all_outs, all_diffs):
            all_outs[out] = all_outs[out][:-pad]
            all_diffs[diff] = all_diffs[diff][:-pad]
    return all_outs, all_diffs


def _Net_set_mean(self, input_, mean_f, mode='image'):
    """
    Set the mean to subtract for data centering.

    Take
    input_: which input to assign this mean.
    mean_f: path to mean .npy
    mode: image = use the whole-image mean (and check dimensions)
          channel = channel constant (i.e. mean pixel instead of mean image)
    """
    if input_ not in self.inputs:
        raise Exception('Input not in {}'.format(self.inputs))
    mean = np.load(mean_f)
    if mode == 'image':
        if mean.shape != self.input.data.shape[1:]:
            raise Exception('The mean shape does not match the input shape.')
        self.mean[input_] = mean
    elif mode == 'channel':
        self.mean[input_] = mean.mean(1).mean(1)
    else:
        raise Exception('Mode not in {}'.format(['image', 'channel']))



def _Net_set_input_scale(self, input_, scale):
    """
    Set the input feature scaling factor s.t. input blob = input * scale.

    Take
    input_: which input to assign this scale factor
    scale: scale coefficient
    """
    if input_ not in self.inputs:
        raise Exception('Input not in {}'.format(self.inputs))
    self.input_scale[input_] = scale


def _Net_set_channel_swap(self, input_, order):
    """
    Set the input channel order for e.g. RGB to BGR conversion
    as needed for the reference ImageNet model.

    Take
    input_: which input to assign this channel order
    order: the order to take the channels.
           (2,1,0) maps RGB to BGR for example.
    """
    if input_ not in self.inputs:
        raise Exception('Input not in {}'.format(self.inputs))
    self.channel_swap[input_] = order


def _Net_caffeinate(self, input_, images):
    """
    Format image for input to Caffe:
    - convert to single
    - resize to input dimensions (preserving number of channels)
    - scale feature
    - reorder channels (for instance color to BGR)
    - subtract mean
    - transpose dimensions to K x H x W

    Take
    image: list of (H' x W' x K) ndarray

    Give
    image: (K x H x W) ndarray
    """
    caffe_images = []
    for im in images:
        caffe_im = im.astype(np.float32)
        input_scale = self.input_scale.get(input_)
        channel_order = self.channel_swap.get(input_)
        mean = self.mean.get(input_)
        in_dims = self.blobs[input_].data.shape[2:]
        if caffe_im.shape[:2] != in_dims:
            scale_h = in_dims[0] / float(caffe_im.shape[0])
            scale_w = in_dims[1] / float(caffe_im.shape[1])
            caffe_im = zoom(caffe_im, (scale_h, scale_w, 1), order=1)
        if input_scale:
            caffe_im *= input_scale
        if channel_order:
            caffe_im = caffe_im[:, :, channel_order]
        if mean:
            caffe_im -= mean
        caffe_im = caffe_im.transpose((2, 0, 1))
        caffe_images.append(caffe_im)
    return np.asarray(caffe_images)


def _Net_decaffeinate(self, input_, images):
    """
    Invert Caffe formatting; see _Net_caffeinate().
    """
    decaf_images = []
    for im in images:
        decaf_im = image.squeeze()
        decaf_im = decaf_im.transpose((1,2,0))
        input_scale = self.input_scale.get(input_)
        channel_order = self.channel_swap.get(input_)
        mean = self.mean.get(input_)
        if mean:
            decaf_im += mean
        if channel_order:
            decaf_im = decaf_im[:, :, channel_order[::-1]]
        if input_scale:
            decaf_im /= input_scale
        decaf_images.append(decaf_im)
    return np.asarray(decaf_images)


def _Net_set_input_arrays(self, data, labels):
    """
    Set input arrays of the in-memory MemoryDataLayer.
    (Note: this is only for networks declared with the memory data layer.)
    """
    if labels.ndim == 1:
        labels = np.ascontiguousarray(labels[:, np.newaxis, np.newaxis,
                                             np.newaxis])
    return self._set_input_arrays(data, labels)


def _Net_batch(self, blobs):
    """
    Batch blob lists according to net's batch size.

    Take
    blobs: Keys blob names and values are lists of blobs (of any length).
           Naturally, all the lists should have the same length.

    Give (yield)
    batch: {blob name: list of blobs} dict for a single batch.
    """
    num = len(blobs.itervalues().next())
    batch_size = self.blobs.itervalues().next().num
    remainder = num % batch_size
    num_batches = num / batch_size

    # Yield full batches.
    for b in range(num_batches):
        for i in [b * batch_size]:
            yield {name: blobs[name][i:i + batch_size] for name in blobs}

    # Yield last padded batch, if any.
    if remainder > 0:
        padded_batch = {}
        for name in blobs:
            padding = np.zeros((remainder,) + blobs[name].shape[1:])
            padded_batch[name] = np.concatenate([blobs[name][-remainder:],
                                                 padding])
        yield padded_batch


# Attach methods to Net.
Net.blobs = _Net_blobs
Net.params = _Net_params
Net.forward = _Net_forward
Net.backward = _Net_backward
Net.forward_all = _Net_forward_all
Net.forward_backward_all = _Net_forward_backward_all
Net.set_mean = _Net_set_mean
Net.set_input_scale = _Net_set_input_scale
Net.set_channel_swap = _Net_set_channel_swap
Net.caffeinate = _Net_caffeinate
Net.decaffeinate= _Net_decaffeinate
Net.set_input_arrays = _Net_set_input_arrays
Net._batch = _Net_batch
