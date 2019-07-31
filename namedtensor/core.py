from .schema import _Schema
import operator
import functools


def prod(factors):
    return functools.reduce(operator.mul, factors, 1)


def assert_match(*tensors):
    sizes = {}
    failure = False
    for t in tensors:
        shape = t.vshape
        for i, k in t._schema.enum_all():
            v = shape[i]
            if v == 1:
                continue
            if k in sizes:
                failure = failure or sizes[k] != v
            else:
                sizes[k] = v
    assert not failure, "Overlapping dim names must match: " + " ".join(
        [str(t.shape) for t in tensors]
    )


class NamedTensorBase:
    """
    Attributes:
        tensor: The raw tensor data
        dims: Tuple of unique dimension names associated with this array.
        ndim: Number of dimensions
        sizes: The raw dimension sizes
        shape: Ordered mapping from dimension names to lengths.
    """

    def __init__(self, tensor, names, mask=0):
        self._tensor = tensor
        self._schema = _Schema.build(names, mask)
        if self._tensor.dim() > 0:
            assert len(self._tensor.shape) == len(self._schema._names), (
                "Tensor has %d dim, but %d names"
                % (len(self._tensor.shape), len(self._schema._names))
            )
        else:
            assert len(names) == 0, str(tensor)

    def __deepcopy__(self, memo):
        new_ntensor = self._new(self._tensor.__deepcopy__(memo))
        memo[id(self)] = new_ntensor
        return new_ntensor

    @property
    def dims(self):
        "Return the dim names for the tensor"
        return tuple(self._schema._names)

    @property
    def vshape(self):
        "The raw dim size for the tensor."
        return tuple(self._tensor.size())

    @property
    def shape(self):
        "The ordered dict of available dimensions."
        return self._schema.ordered_dict(self._tensor.size())

    def __repr__(self):
        return "NamedTensor(\n\t%s,\n\t%s)" % (
            self._tensor,
            self._schema._names,
        )

    def size(self, dim):
        "Return the raw shape of the tensor"
        i = self._schema.get(dim)
        return self._tensor.size(i)

    def assert_size(self, **kwargs):
        "Return the raw shape of the tensor"
        for dim, v in kwargs.items():
            i = self._schema.get(dim)
            assert self._tensor.size(i) == v, (
                "Size of %s should be %d, got %d"
                % (dim, v, self._tensor.size(i))
            )
        return self

    @property
    def values(self):
        "The raw underlying tensor object."
        return self._tensor

    def _new(self, tensor, drop=None, add=None, updates={}, mask=None):
        return self.__class__(
            tensor,
            self._schema.drop(drop).update(updates)._names
            + (() if not add else add),
            self._schema._masked if mask is None else mask,
        )

    def _to_einops(self):
        return self._schema._to_einops()

    def mask_to(self, name):
        if name == "":
            return self._new(self._tensor, mask=0)
        else:
            return self._new(self._tensor, mask=self._schema.get(name) + 1)

    def stack(self, dims, name):
        "Stack any number of existing dimensions into a single new dimension."
        for dim in dims:
            self._schema.get(dim)
        return self._merge(dims, name)

    def unsqueeze(self, dim):
        "Create new dimension of size one."
        return self._split(self._schema._names[0], (dim, self._schema._names[0]), {dim: 1})

    def split(self, dim, names, **dim_sizes):
        "Split an of existing dimension into new dimensions."
        return self._split(dim, names, dim_sizes)

    def rename(self, dim, name):
        "Rename a dimension."
        return self._split(dim, (name,), {})

    def transpose(self, *dims):
        "Return a new DataArray object with transposed dimensions."
        for dim in dims:
            self._schema.get(dim)
        to_dims = (
            tuple((d for d in self._schema._names if d not in dims)) + dims
        )
        indices = [self._schema.get(d) for d in to_dims]
        tensor = self._tensor.permute(*indices)
        return self.__class__(tensor, to_dims)

    # Todo: fix arg names
    def _merge(self, names, dim):
        s = []
        ex = []
        first = True
        view = []
        for d in self._schema._names:
            if d not in names:
                s.append(d)
                ex.append(d)
                view.append(self.shape[d])
            elif first:
                s += names
                view.append(prod([self.shape[d2] for d2 in names]))
                ex.append(dim)
                first = False
        tensor = self.transpose(*s)._tensor.contiguous().view(*view)
        return self.__class__(tensor, ex)

    def _split(self, dim, names, size_dict):
        query = []
        ex = []
        view = []
        for i, d in self._schema.enum_all():
            if d != dim:
                query.append(d)
                ex.append(d)
                view.append(self.shape[d])
            else:
                query += names
                for d2 in names:
                    view.append(size_dict.get(d2, -1))
                ex += names
        return self.__class__(self._tensor.view(*view), ex)

    def __len__(self):
        return len(self._tensor)

    def _promote(self, dims):
        "Move dims to the front of the line"
        term = [
            d for d in self._schema._names if d not in dims
        ] + dims.split()[1:]

        return self.transpose(*term)

    def _force_order(self, names):
        """ Forces self to take order in names, adds 1-size dims if needed """
        ex = []
        view = []
        trans = []
        for d in names:
            if d not in self._schema._names:
                ex.append(d)
                view.append(1)
            else:
                ex.append(d)
                view.append(self.shape[d])
                trans.append(d)
        return self.__class__(
            self.transpose(*trans)._tensor.contiguous().view(*view), ex
        )

    def _broadcast_order(self, other_names):
        """ Outputs a shared order (list) that works for self and other """
        order = []
        for d in other_names:
            if d not in self._schema._names:
                order.append(d)
        for d in self._schema._names:
            order.append(d)
        return order

    def _mask_broadcast_order(self, main_names):
        """
        If broadcasting possible from self (mask) to main, outputs a shared order.
        Otherwise errors and prints dimensions that exist in mask but not in main.
        """

        to_be_broadcasted = set(self._schema._names)
        broadcasted_to = set(main_names)

        diff = to_be_broadcasted.difference(broadcasted_to)
        diff_string = ", ".join(diff)

        assert len(diff) == 0, (
            "Attemped to broadcast mask but unable to broadcast dimensions %s"
            % diff_string
        )

        return main_names
