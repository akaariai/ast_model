from django.db import models
from django.db.models import signals
from astmodelbase import ASTModelBase

class Foo10(models.Model):
    __metaclass__ = ASTModelBase

    f1 = models.IntegerField()
    f2 = models.IntegerField()
    f3 = models.IntegerField()
    f4 = models.IntegerField()
    f5 = models.IntegerField()
    f6 = models.IntegerField()
    f7 = models.IntegerField()
    f8 = models.IntegerField()
    f9 = models.IntegerField()
    f10 = models.IntegerField()

class SignalsModel(models.Model):
    """
    A model used only for registering signals to _another_ model than Foo10
    """
    pass

def somefunc(*args, **kwargs):
    pass

signals.pre_init.connect(SignalsModel, somefunc)
signals.post_init.connect(SignalsModel, somefunc)
