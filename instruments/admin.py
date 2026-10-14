from django.contrib import admin

from .models import Derived, Instrument, InstrumentVersion, Item, Section

admin.site.register([Instrument, InstrumentVersion, Section, Item, Derived])
