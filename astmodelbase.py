from django.db.models import Model
from django.db.models.base import ModelBase
from django.db.models import Field
import ast

class ASTModelBase(ModelBase):
    """
    A class using ASTModelBase will use a custom __init__ method. The
    properties of the custom __init__ are as follows:
        - Signals are not sent. This is done by hand-editing the original
          __init__ source.
        - If there is exactly as much args to __init__ as it has fields
          a fast path is taken. The fast path is a rewrite of:
              for attname, val in izip(attnames, args):
                  setattr(self, attname, val)
          into this:
              self.att1, self.att2, self.att3, ... = args
        - Otherwise the init method should work normally. Although this is
          _very_ experimental.

    ASTModelBase can not be used with any model which has GenericForeignKey
    or ImageFields. The working of those fields is based on pre_init/post_init
    signals. There is no checking if these fields are present. ImageField
    should actually work if you don't have width/height DB fields.

    On Python 2.6, in a project that has both pre_init and post_init signals
    in use to some model (not necessarily the current model) the speedup for
    Foo2.objects.all()[0:10000] is X, where Foo has fields id, val1, and val2.
    For Foo10(objects.all()[0:10000] the speedup is Y, where Foo10 has id +
    10 fields. The test is done on in-memory SQLite database.

    AST is used to dynamically alter the original Model.__init__ into a new
    __init__ method which has the abovementioned optimizations done. The AST
    generation has a lot of comments, so it should be possible to follow what
    is done.

    Requirements: Python 2.6 or Python 2.7. Tested also on PyPy 1.6 nightly
    (2011-10-15). There is no Python 3 support in Django, but the AST part
    should work with minor modifications.

    Usage:
    class SomeModel(models.Model):
        __metaclass__ = ASTModelBase

    Known bugs and limitations:
      - Eats your data. In other words, not tested at all. Use at your own
        risk.
      - Changes made to the original __init__ are not reflected here. The
        django_init_src will need to be updated, and in addition to that, the
        validity of the AST transforms need to be checked. It is likely that
        this source code will not be updated when Django is updated. The
        Django version used for testing is trunk HEAD as of 2011-11-13.

    It might be more portable, and easier, to just dynamically alter the
    source code instead of going the AST route. But I wanted to learn AST...
    """

    def _create_ast_init(cls):
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
    
        # We need a context where everything necessary for the normal
        # __init__ is included. Lets start from the builtins, without those
        # things like len() are not available.
        init_context = {}
        init_context.update(__builtins__)

        # Next, lets import things that are needed by the init into the
        # context.
        # TODO: Can we import these in the django_init_src directly?
        from django.db.models.base import ModelState
        from itertools import izip
        from django.db.models.query_utils import DeferredAttribute
        init_context['izip'] = izip
        init_context['ModelState'] = ModelState
        init_context['DeferredAttribute'] = DeferredAttribute
        init_ast = ast.parse(django_init_src)

        # Before we start modifying the AST, lets create some nodes we will be
        # needing. We need the self.f1, self.f2, ... = args part of the code.
        # The below code is here just so that it is easy to see what the
        # assignment AST should look like.
        field_assign_ast = ast.parse(field_assign_src)
        #print ast.dump(field_assign_ast)

        # Create some reusable nodes.
        store = ast.Store()
        load = ast.Load()
        # Lets work the new AST from inside out, the innermost nodes are:
        # Attribute(value=Name(id='self', ctx=Load()), attr='f1', ctx=Store())
        attrs = []
        for field in cls._meta.fields:
            name = ast.Name(id='self', ctx=load)
            attr = ast.Attribute(value=name, attr=field.attname, ctx=store)
            attrs.append(attr)
        # Now transform that into "store" tuple
        tuple = ast.Tuple(elts=attrs, ctx=store)
        # We are storing the args into that tuple
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

    def add_to_class(cls, name, value):
        """
        Whenever a new field is added to the ASTModelBase, we need to recreate
        the __init__ method.
        """
        # TODO: we could enforce no GenericForeignKeys / ImageFields
        # We could also make the ASTed __init__ send the needed signals if
        # GenericForeignKey is present.
        
        # 1. Add the field normally to the model, so that the options.fields
        # iterator is usable. AST modification depends on the fields iterator
        # being present.
        super(ASTModelBase, cls).add_to_class(name, value)

        # 2. assign the asted method if we were adding a field.
        if isinstance(value, Field):
            # There is probably a concurrency issue here - user might access
            # the old init at this point, but the field is already added. I
            # don't know if this is something to worry about.
            new_init = cls._create_ast_init()

            # TODO: we should really test the new init here...
            cls.__init__ = new_init
        # That's it folks.

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
            print e
            #print ast.dump(node)
            return node

django_init_src = """
# This is the django.db.models.base.Model.__init__ method. The method has
# some comments starting with AST noting what we are going to change.
# Signals have been removed by hand. They could be removed 

def __init__(self, *args, **kwargs):
    # Set up the storage for instance state
    self._state = ModelState()

    # AST: we are going to rewrite the -999 below, and also the pass into
    # self.field1, self.field2, ... = args.
    if len(args) == -999:
        self.__dict__.update(izip(
            ['id', 'f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f7', 'f8', 'f9', 'f10'],
            args))
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
"""

field_assign_src = """
self.f1, self.f2 = args
"""

