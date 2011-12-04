from datetime import datetime
from django.db.transaction import commit_on_success
from django.db import connection
from obj_creation_speed.models import Foo10, FooExt2, FooExt1, SignalsModel
DATA_COUNT = 10000
ITERATIONS = 10

@commit_on_success
def create_data(count):
    print "deleting / creating test data"
    while Foo10.objects.count() > 0:
        Foo10.objects.filter(pk__in=Foo10.objects.all()[0:500]).delete()
    for i in range(0, count):
        Foo10(*([i]*len(Foo10._meta.fields))).save()
# Needed only on first run
create_data(DATA_COUNT)

for _ in range(0, ITERATIONS):
    start = datetime.now()
    for i in range(0, DATA_COUNT):
        args = [i] * len(Foo10._meta.fields)
        Foo10(*args)
    print('Time for %d raw inits %s' % (DATA_COUNT, datetime.now() - start))
    
    start = datetime.now()
    for pos, obj in enumerate(Foo10.objects.all().order_by('id')):
        pass
    print('Time for %d objs from DB %s' % (DATA_COUNT, datetime.now() - start))
    
    start = datetime.now()
    cursor = connection.cursor()
    cursor.execute("select * from obj_creation_speed_foo10")
    for row in cursor.fetchall():
        pass
    print('Time for %d objs with raw SQL %s' % (DATA_COUNT, datetime.now() - start))
