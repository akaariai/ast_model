from django.db import models
from django.db.models import signals
from astmodel import ASTModel

class Foo10(ASTModel):
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

# Some testing models...
class FooExt1(Foo10):
    pk2 = models.IntegerField(primary_key=True)

class FooExt2(FooExt1):
    pass

class FooFK(models.Model):
    fk = models.ForeignKey(Foo10, related_name='fk_set')

class SignalsModel(models.Model):
    #A model used only for registering signals to _another_ model than Foo10
    pkf = models.CharField(max_length=10, primary_key=True, editable=False)
    pass

def somefunc(*args, **kwargs):
    pass

signals.pre_init.connect(SignalsModel, somefunc)
signals.post_init.connect(SignalsModel, somefunc)
