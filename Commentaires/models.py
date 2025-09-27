from django.db import models
import re
from django.utils import timezone
from dateutil import parser as date_parser
from django.core.validators import MinLengthValidator


#----------------------------------------------------------------------------------------------------------------------------  
class Article(models.Model):    
    """Modèle pour stocker les informations des articles"""
    
    # Identifiants
    article_id = models.CharField(max_length=50,unique=True,verbose_name="ID de l'article",help_text="ID unique de l'article extrait de l'URL")

    # Métadonnées de l'article
    titre = models.TextField(verbose_name="Titre de l'article",help_text="Titre complet de l'article")
    url = models.URLField(max_length=500,verbose_name="URL de l'article",help_text="Lien vers l'article original")
    date_publication = models.CharField(max_length=100,verbose_name="Date de publication",help_text="Date de publication originale de l'article")
    categorie = models.CharField(max_length=200,blank=True,null=True,verbose_name="Catégorie",help_text="Catégorie ou rubrique de l'article")   

    
    # Métadonnées de scraping
    date_scraping = models.DateTimeField(default=timezone.now,verbose_name="Date du scraping",help_text="Date et heure du scraping de l'article")
    
    # Champs calculés (pour optimisation)
    nombre_commentaires = models.PositiveIntegerField(default=0,verbose_name="Nombre de commentaires",help_text="Nombre total de commentaires pour cet article")
    nombre_reponses = models.PositiveIntegerField(default=0,verbose_name="Nombre de réponses",help_text="Nombre total de réponses aux commentaires")

    class Meta:
        verbose_name = "Article"
        verbose_name_plural = "Articles"
        ordering = ['-date_scraping']
        indexes = [
            models.Index(fields=['article_id']),
            models.Index(fields=['date_scraping']),
            models.Index(fields=['categorie']),
        ]

    def __str__(self):
        return f"{self.article_id} - {self.titre[:50]}..."

    def total_interventions(self):
        return self.nombre_commentaires + self.nombre_reponses

    def update_statistiques(self):
        from django.db.models import Count, Q
        
        stats = self.commentaires.aggregate(
            total_commentaires=Count('id', filter=Q(type=Commentaire.TYPE_COMMENTAIRE)),
            total_reponses=Count('id', filter=Q(type=Commentaire.TYPE_REPONSE))
        )
        
        self.nombre_commentaires = stats['total_commentaires'] or 0
        self.nombre_reponses = stats['total_reponses'] or 0
        self.save()

#----------------------------------------------------------------------------------------------------------------------------  
class Commentaire(models.Model):
    """Modèle pour stocker les commentaires et réponses"""
    
    # Types de commentaires
    TYPE_COMMENTAIRE = 'commentaire'
    TYPE_REPONSE = 'reponse'
    TYPE_CHOICES = [
        (TYPE_COMMENTAIRE, 'Commentaire principal'),
        (TYPE_REPONSE, 'Réponse à un commentaire'),
    ]

    # Relations
    article = models.ForeignKey(Article,on_delete=models.CASCADE,related_name='commentaires',verbose_name="Article associé",help_text="Article auquel ce commentaire est lié" )
    
    parent = models.ForeignKey('self',on_delete=models.CASCADE,related_name='reponses',blank=True,null=True,verbose_name="Commentaire parent",help_text="Commentaire auquel cette réponse est associée")

    # Identifiants
    commentaire_id = models.CharField(max_length=100,verbose_name="ID du commentaire",help_text="ID unique du commentaire (format: C001, C001R01, etc.)")
    
    # Contenu
    auteur = models.CharField(max_length=200,verbose_name="Auteur du commentaire",help_text="Nom ou pseudonyme de l'auteur")
    date_publication = models.CharField(max_length=100,verbose_name="Date de publication",help_text="Date de publication originale du commentaire")
    contenu = models.TextField(verbose_name="Contenu du commentaire",help_text="Texte complet du commentaire",validators=[MinLengthValidator(5)])
    
    # Métadonnées techniques
    type = models.CharField(max_length=15,choices=TYPE_CHOICES,verbose_name="Type d'intervention")
    longueur_contenu = models.PositiveIntegerField(verbose_name="Longueur du contenu",help_text="Nombre de caractères dans le commentaire")
    mots_contenu = models.PositiveIntegerField(verbose_name="Nombre de mots",help_text="Nombre de mots dans le commentaire")
    
    contenu_propre = models.TextField(verbose_name="Contenu nettoyé",help_text="Texte du commentaire après nettoyage (HTML, espaces, etc.)")
    longueur_contenu_propre = models.PositiveIntegerField(verbose_name="Longueur du contenu nettoyé",help_text="Nombre de caractères dans le contenu nettoyé")
    mots_contenu_propre = models.PositiveIntegerField(verbose_name="Nombre de mots nettoyé",help_text="Nombre de mots dans le contenu nettoyé")

    # Métadonnées de scraping
    date_extraction = models.DateTimeField(default=timezone.now,verbose_name="Date d'extraction",help_text="Date et heure du scraping du commentaire")

    # Champs calculés
    nombre_reponses = models.PositiveIntegerField(default=0,verbose_name="Nombre de réponses",help_text="Nombre de réponses à ce commentaire")

    class Meta:
        verbose_name = "Commentaire"
        verbose_name_plural = "Commentaires"
        ordering = ['article', 'commentaire_id']
        # unique_together = ['article', 'commentaire_id']
        indexes = [
            models.Index(fields=['article', 'type']),
            models.Index(fields=['auteur']),
            models.Index(fields=['date_publication']),
            models.Index(fields=['longueur_contenu']),
        ]

    def __str__(self):
        return f"{self.commentaire_id} - {self.auteur} - {self.contenu[:50]}..."

    def est_commentaire_principal(self):
        """Vérifie si c'est un commentaire principal (sans parent)"""
        return self.type == self.TYPE_COMMENTAIRE and self.parent is None

    def est_reponse(self):
        """Vérifie si c'est une réponse à un commentaire"""
        return self.type == self.TYPE_REPONSE

    def save(self, *args, **kwargs):
        # Sauvegarde initiale pour avoir un PK
        is_new = self.pk is None
        super().save(*args, **kwargs)

        # Mise à jour automatique des champs calculés uniquement si nécessaire
        if self.est_commentaire_principal():
            self.nombre_reponses = self.reponses.count()
            # Éviter boucle infinie : update_fields pour ne pas rappeler save() entièrement
            if not is_new:
                super().save(update_fields=['nombre_reponses'])

        # Mise à jour des statistiques de l'article
        if self.article:
            self.article.update_statistiques()


#----------------------------------------------------------------------------------------------------------------------------  
class URLStorage(models.Model):
    """Stockage des URLs à scraper"""
    EN_ATTENTE = 'attente'
    EN_COURS = 'cours'
    TERMINE = 'termine'
    ERREUR = 'erreur'
    
    STATUT_CHOICES = [
        (EN_ATTENTE, 'En attente'),
        (EN_COURS, 'En cours de scraping'),
        (TERMINE, 'Terminé'),
        (ERREUR, 'Erreur'),
    ]
    
    url = models.URLField(max_length=500)
    article = models.ForeignKey('Article', on_delete=models.SET_NULL, null=True, blank=True)
    statut = models.CharField(max_length=10, choices=STATUT_CHOICES, default=EN_ATTENTE)
    date_ajout = models.DateTimeField(auto_now_add=True)
    date_maj = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['url']
        ordering = ['-date_ajout']

class ScrapingHistory(models.Model):
    """Historique des opérations de scraping"""
    EN_COURS = 'cours'
    TERMINE = 'termine'
    ERREUR = 'erreur'

    STATUT_CHOICES = [
        (EN_COURS, 'En cours'),
        (TERMINE, 'Terminé'),
        (ERREUR, 'Erreur'),
    ]

    urls_selectionnees = models.TextField()
    statut = models.CharField(max_length=10, choices=STATUT_CHOICES, default=EN_COURS)
    date_lancement = models.DateTimeField(auto_now_add=True)
    date_fin = models.DateTimeField(null=True, blank=True)
    erreur = models.TextField(null=True, blank=True)
    progression = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-date_lancement']

            
            
            
        