from django.contrib import admin
from django.urls import path, include

admin.site.site_title = "Projet NLP Groupe 9 Master FD&IA 2025"
admin.site.site_header = "Projet NLP Groupe 9 Master FD&IA 2025"
admin.site.index_title = "Projet NLP Groupe 9 Master FD&IA 2025"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('Commentaires.urls')),
]
