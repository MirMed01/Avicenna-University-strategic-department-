from django.contrib import admin

from .models import Assessment, Cycle, EvidenceFile

admin.site.register([Cycle, Assessment, EvidenceFile])
