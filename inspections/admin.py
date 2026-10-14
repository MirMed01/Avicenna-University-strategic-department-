from django.contrib import admin

from .models import Finding, Inspection, Result, Task

admin.site.register([Inspection, Task, Result, Finding])
