from django.core.management import setup_environ
import settings
setup_environ(settings)

from datetime import datetime
from django.db.transaction import commit_on_success
from obj_creation_speed.models import Foo10

DATA_COUNT = 30000
ITERATIONS = 3

@commit_on_success
def create_data(count):
    Foo10.objects.all().delete()
    for i in range(0, count):
        Foo10(*([i]*11)).save()
# Needed only on first run
create_data(DATA_COUNT)

for _ in range(0, ITERATIONS):
    start = datetime.now()
    for i in range(0, DATA_COUNT):
        Foo10(1, i, i, i, i, i, i, i, i, i, i)
    print('Time for %d raw inits %s' % (DATA_COUNT, datetime.now() - start))

    start = datetime.now()
    for obj in Foo10.objects.all():
        pass
    # When using chunked iterator from
    # https://github.com/akaariai/django/tree/chunked
    #for obj in Foo10.objects.all().chunked():
    #    pass
    print('Time for %d objs from DB %s' % (DATA_COUNT, datetime.now() - start))
