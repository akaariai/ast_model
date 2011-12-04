from django.db.models import Model
from django.db.models.base import ModelBase
from django.db.models import Field
import ast

class ASTModel(Model):
    """
    A class deriving from ASTModel will use a custom __init__ method. The
    properties of the custom __init__ are as follows:
        - Signals are sent only when needed.
        - If there is exactly as much args to __init__ as it has fields
          a fast path is taken. The fast path is a rewrite of:
              for attname, val in izip(attnames, args):
                  setattr(self, attname, val)
          into this:
              self.att1, self.att2, self.att3, ... = args
        - Otherwise the init method should work normally. Although this is
          _very_ experimental.

    AST is used to dynamically alter the original Model.__init__ into a new
    __init__ method which has the abovementioned optimizations done. The AST
    generation has a lot of comments, so it should be possible to follow what
    is done.

    Requirements: Python 2.6 or Python 2.7.

    Usage:
        from astmodel import ASTModel
        class SomeModel(ASTModel):
            # If you want to force init signal sending, then set
            # send_init_signals = True
            # otherwise, init_signals are sent only if the Model
            # contains ImageFields or GenericForeignKeys. 
            normal class definition otherwise
                                              

    Known bugs and limitations:
      - Eats your data. In other words, not tested at all. Use at your own
        risk.

    I have tested this on Django trunk as of 2011-12-04, all tests passed.
    """
    __metaclass__ = ASTModelBase
    send_init_signals = False

    def __init__(self, *args, **kwargs):
        try:
            self._asted_init(*args, **kwargs)
        except AttributeError:
            new_init = self._create_ast_init()
            self.__class__._asted_init = new_init
            for field in self._meta.fields:
                if (isinstance(field, GenericForeignKey)
                    or isinstance(field, ImageField)):
                    self.send_init_signals = True
            self._asted_init(*args, **kwargs)

    def _create_ast_init(self):
        """
        This method will read in the _django_init_src, which is a string
        containing a modified version of the normal Model __init__() method.
 
        If you need to make changes into AST generation, the easiest way to
        get started is to write by hand the new code for a instance of the
        new __init__ definition you want, and then do:

            new_ast = ast.parse(new_src); ast.dump(new_ast)

        The dump will give a clue how the AST should look like.
 
        There is source included for:

            self.f1, self.f2 = args
        
        in field_assign_src.
        """
        cls = self.__class__
        # We need a context where everything necessary for the normal
        # __init__ is included. Lets start from the builtins, without those
        # things like len() are not available.
        init_context = {}
        init_context.update(__builtins__)

        init_ast = ast.parse(django_init_src)

        # Before we start modifying the AST, lets create some nodes we will be
        # needing. We need the self.f1, self.f2, ... = args part of the code.

        # Create some reusable nodes.
        store = ast.Store()
        load = ast.Load()
        # Lets work the new AST from inside out, the innermost nodes are:
        # Attribute(value=Name(id='self', ctx=Load()), attr='f1', ctx=Store())
        # We create a list of them, after this we have the left side:
        # self.f1, self.f2, self.f3, ...
        attrs = []
        for field in cls._meta.fields:
            name = ast.Name(id='self', ctx=load)
            attr = ast.Attribute(value=name, attr=field.attname, ctx=store)
            attrs.append(attr)
        # Now transform that into "store" tuple
        tuple = ast.Tuple(elts=attrs, ctx=store)
        # We are storing the args into that tuple
        # (create the = args part)
        args = ast.Name(id='args', ctx=load)
        assign = ast.Assign(targets=[tuple], value=args)
        # Now the self.f1, ... = args part is ready. We need still to rewrite
        # the -999 to the value of len(fields).

        # Lets use the ast.NodeTransformer for rewriting. The RewriteInit node
        # transformer is defined below this class.
        rewriter = RewriteInit(new_if_body=[assign],
                               len_fields=len(cls._meta.fields))
        init_ast = rewriter.visit(init_ast)
        ast.fix_missing_locations(init_ast)

        # Compile the ast, exec it and then return it from the context
        # (executing it saves the function in the context).
        init_compiled = compile(init_ast, '<string>', 'exec')
        exec init_compiled in init_context
        return init_context['__init__']


class RewriteInit(ast.NodeTransformer):
    def __init__(self, new_if_body, len_fields):
        self.new_if_body = new_if_body
        self.len_fields = len_fields

    def visit_If(self, node):
        try:
            if node.test.comparators[0].n == -999:
                #print ast.dump(node.body[0])
                #print ast.dump(node.test)
                test = ast.Compare(left=node.test.left, ops=node.test.ops,
                                comparators=[ast.Num(n=self.len_fields)])
                newif = ast.If(test=test, body=self.new_if_body,
                               orelse=node.orelse)
                return newif
            return node
        except Exception, e:
            raise e 
            #print e
            #print ast.dump(node)
            return node

django_init_src = """
# This is the django.db.models.base.Model.__init__ method. The method has
# some comments starting with AST noting what we are going to change.
# Signals have been removed by hand. They could be removed 
from django.db.models import Model
from django.db.models.base import ModelState
from django.db.models.fields.related import ManyToOneRel
from django.db.models.query_utils import DeferredAttribute
from django.db.models.signals import pre_init, post_init

from itertools import izip

def __init__(self, *args, **kwargs):
    # Set up the storage for instance state
    if self.send_init_signals:
        pre_init.send(sender=self.__class__, args=args, kwargs=kwargs)
    self._state = ModelState()

    # AST: we are going to rewrite the -999 below to actual field count.
    # What is contained in the if branch will be rewritten into:
    # self.field1, self.field2, ... = args.
    # The constant -999 is a marker for ast generation.
    if len(args) == -999:
        pass
    else:
        # Fall through to original __init__ code.

        # There is a rather weird disparity here; if kwargs, it's set, then args
        # overrides it. It should be one or the other; don't duplicate the work
        # The reason for the kwargs check is that standard iterator passes in by
        # args, and instantiation for iteration is 33% faster.
        args_len = len(args)
        if args_len > len(self._meta.fields):
            # Daft, but matches old exception sans the err msg.
            raise IndexError("Number of args exceeds number of fields")

        fields_iter = iter(self._meta.fields)
        if not kwargs:
            # The ordering of the izip calls matter - izip throws StopIteration
            # when an iter throws it. So if the first iter throws it, the second
            # is *not* consumed. We rely on this, so don't change the order
            # without changing the logic.
            for val, field in izip(args, fields_iter):
                setattr(self, field.attname, val)
        else:
            # Slower, kwargs-ready version.
            for val, field in izip(args, fields_iter):
                setattr(self, field.attname, val)
                kwargs.pop(field.name, None)
                # Maintain compatibility with existing calls.
                if isinstance(field.rel, ManyToOneRel):
                    kwargs.pop(field.attname, None)

        # Now we're left with the unprocessed fields that *must* come from
        # keywords, or default.

        for field in fields_iter:
            is_related_object = False
            # This slightly odd construct is so that we can access any
            # data-descriptor object (DeferredAttribute) without triggering its
            # __get__ method.
            if (field.attname not in kwargs and
                    isinstance(self.__class__.__dict__.get(field.attname), DeferredAttribute)):
                # This field will be populated on request.
                continue
            if kwargs:
                if isinstance(field.rel, ManyToOneRel):
                    try:
                        # Assume object instance was passed in.
                        rel_obj = kwargs.pop(field.name)
                        is_related_object = True
                    except KeyError:
                        try:
                            # Object instance wasn't passed in -- must be an ID.
                            val = kwargs.pop(field.attname)
                        except KeyError:
                            val = field.get_default()
                    else:
                        # Object instance was passed in. Special case: You can
                        # pass in "None" for related objects if it's allowed.
                        if rel_obj is None and field.null:
                            val = None
                else:
                    try:
                        val = kwargs.pop(field.attname)
                    except KeyError:
                        # This is done with an exception rather than the
                        # default argument on pop because we don't want
                        # get_default() to be evaluated, and then not used.
                        # Refs #12057.
                        val = field.get_default()
            else:
                val = field.get_default()
            if is_related_object:
                # If we are passed a related instance, set it using the
                # field.name instead of field.attname (e.g. "user" instead of
                # "user_id") so that the object gets properly cached (and type
                # checked) by the RelatedObjectDescriptor.
                setattr(self, field.name, rel_obj)
            else:
                setattr(self, field.attname, val)

        if kwargs:
            for prop in kwargs.keys():
                try:
                    if isinstance(getattr(self.__class__, prop), property):
                        setattr(self, prop, kwargs.pop(prop))
                except AttributeError:
                    pass
            if kwargs:
                raise TypeError("'%s' is an invalid keyword argument for this function" % kwargs.keys()[0])
    super(Model, self).__init__()
    if self.send_init_signals:
        post_init.send(sender=self.__class__, instance=self)
"""

