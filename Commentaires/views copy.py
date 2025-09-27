from django.shortcuts import render, redirect
from django.views import View
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.db import transaction
import pandas as pd
from datetime import datetime
import json
import threading
import time

from .models import *
from .lefaso_scraper import LefasoCommentScraper

class Home(View):
    template_name = "Commentaires/index.html"
    
    def get(self, request, *args, **kwargs):
        # Récupérer les URLs déjà enregistrées
        urls_enregistrees = URLStorage.objects.all().order_by('-date_ajout')
        
        # Récupérer l'historique des scrapings
        historiques = ScrapingHistory.objects.all().order_by('-date_lancement')[:10]
        
        # Statistiques
        total_articles = Article.objects.count()
        total_commentaires = Commentaire.objects.count()
        
        context = {
            'urls_enregistrees': urls_enregistrees,
            'historiques': historiques,
            'total_articles': total_articles,
            'total_commentaires': total_commentaires,
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action')
        print(action)
        if action == 'ajouter_url':
            return self.ajouter_url(request)
        elif action == 'scraper_urls':
            urls_selectionnees = request.POST.getlist('urls_selectionnees')
            if not urls_selectionnees:
                messages.warning(request, "Veuillez sélectionner au moins une URL pour le scraping")
                return redirect('Commentaires:home')
            return self.lancer_scraping(request)
        elif action == 'supprimer_url':
            url_id = request.POST.get('url_id')
            if not url_id:
                messages.error(request, "Aucune URL spécifiée pour la suppression")
                return redirect('Commentaires:home')
            return self.supprimer_url(request)
        else:
            messages.error(request, "Action non reconnue")
            return redirect('Commentaires:home')

    def ajouter_url(self, request):
        """Ajoute une URL à la liste des URLs à scraper"""
        url = request.POST.get('url', '').strip()
        
        if not url:
            messages.error(request, "Veuillez entrer une URL valide")
            return redirect('Commentaires:home')
        
        # Validation de l'URL LeFaso.net
        if not url.startswith('https://lefaso.net/spip.php?article'):
            messages.error(request, "URL invalide. Doit être une URL d'article LeFaso.net")
            return redirect('Commentaires:home')
        
        # Vérifier si l'URL existe déjà
        if URLStorage.objects.filter(url=url).exists():
            messages.warning(request, "Cette URL est déjà dans votre liste")
            return redirect('Commentaires:home')
        
        # Vérifier si l'article existe déjà en base
        article_id = self.extract_article_id(url)
        if Article.objects.filter(article_id=article_id).exists():
            messages.info(request, "Cet article a déjà été scrapé précédemment")
        
        # Enregistrer l'URL
        URLStorage.objects.create(
            url=url,
            # article_id=article_id,
            statut=URLStorage.EN_ATTENTE
        )
        
        messages.success(request, "URL ajoutée avec succès à votre liste")
        return redirect('Commentaires:home')

    def lancer_scraping(self, request):
        """Lance le scraping des URLs sélectionnées"""
        urls_selectionnees = request.POST.getlist('urls_selectionnees')
        print(urls_selectionnees)
        if not urls_selectionnees:
            messages.error(request, "Veuillez sélectionner au moins une URL à scraper")
            return redirect('Commentaires:home')
        
        # Créer un historique de scraping
        historique = ScrapingHistory.objects.create(
            urls_selectionnees=json.dumps(urls_selectionnees),
            statut=ScrapingHistory.EN_COURS
        )
        
        # Lancer le scraping en arrière-plan (thread)
        thread = threading.Thread(
            target=self.executer_scraping_background,
            args=(urls_selectionnees, historique.id)
        )
        thread.daemon = True
        thread.start()
        
        messages.info(request, f"Scraping lancé pour {len(urls_selectionnees)} URL(s). Cette opération peut prendre quelques minutes.")
        return redirect('Commentaires:home')

    def executer_scraping_background(self, urls, historique_id):
        """Exécute le scraping en arrière-plan"""
        historique = ScrapingHistory.objects.get(id=historique_id)
        
        scraper = LefasoCommentScraper()
        resultats = []
        
        try:
            for i, url in enumerate(urls, 1):
                try:
                    # Mettre à jour le statut de l'URL
                    url_storage = URLStorage.objects.get(url=url)
                    url_storage.statut = URLStorage.EN_COURS
                    url_storage.save()
                    
                    # Exécuter le scraping
                    data = scraper.scrape_article_comments(url)

                    if data and not data.get('erreur'):
                        # Enregistrer dans la base
                        print("data sauvegarde scrap articleaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
                        article_sauvegarde = self.sauvegarder_dans_base(data)
                        print("data sauvegarde scrap article")
                        print(article_sauvegarde)
                        resultat = {
                            'url': url,
                            'statut': 'succes',
                            'article_id': article_sauvegarde.article_id,
                            'commentaires': len(data.get('commentaires', [])),
                            'reponses': data['statistiques'].get('total_reponses', 0)
                        }
                        
                        url_storage.statut = URLStorage.TERMINE
                        url_storage.article = article_sauvegarde
                        url_storage.save()
                        
                    else:
                        resultat = {
                            'url': url,
                            'statut': 'erreur',
                            'erreur': data.get('erreur', 'Erreur inconnue')
                        }
                        url_storage.statut = URLStorage.ERREUR
                        url_storage.save()
                    
                    resultats.append(resultat)
                    
                    # Mettre à jour la progression
                    historique.progression = int((i / len(urls)) * 100)
                    historique.save()
                    
                    # Pause pour éviter de surcharger le serveur
                    time.sleep(2)
                    
                except Exception as e:
                    resultat = {
                        'url': url,
                        'statut': 'erreur',
                        'erreur': str(e)
                    }
                    resultats.append(resultat)
                    
                    url_storage = URLStorage.objects.get(url=url)
                    url_storage.statut = URLStorage.ERREUR
                    url_storage.save()
            
            # Finaliser l'historique
            historique.statut = ScrapingHistory.TERMINE
            historique.resultats = json.dumps(resultats)
            historique.date_fin = timezone.now()
            historique.save()
            
        except Exception as e:
            historique.statut = ScrapingHistory.ERREUR
            historique.erreur = str(e)
            historique.save()

    @transaction.atomic
    def sauvegarder_dans_base(self, data):
        """Sauvegarde les données scrapées dans la base de données"""
        article_info = data['article']
        commentaires_data = data['commentaires']
        stats = data['statistiques']
        
        # Créer ou mettre à jour l'article
        article, created = Article.objects.update_or_create(
            article_id=self.extract_article_id(article_info['url']),
            defaults={
                'titre': article_info.get('titre', ''),
                'url': article_info.get('url', ''),
                'date_publication': article_info.get('date_publication', ''),
                'categorie': article_info.get('categorie', ''),
                'date_scraping': timezone.now(),
                'nombre_commentaires': stats.get('total_commentaires', 0),
                'nombre_reponses': stats.get('total_reponses', 0),
            }
        )
        
        # Sauvegarder les commentaires
        for comment_data in commentaires_data:
            # Commentaire principal
            commentaire = Commentaire.objects.create(
                article=article,
                commentaire_id=f"C{comment_data['id_commentaire']:03d}",
                auteur=comment_data['auteur'],
                date_publication=comment_data['date_publication'],
                contenu=comment_data['contenu'],
                type=Commentaire.TYPE_COMMENTAIRE,
                longueur_contenu=comment_data['longueur_contenu'],
                mots_contenu=comment_data['mots_contenu'],
                date_extraction=timezone.now(),
            )
            
            # Réponses au commentaire
            for reponse_data in comment_data.get('reponses', []):
                Commentaire.objects.create(
                    article=article,
                    parent=commentaire,
                    commentaire_id=f"C{comment_data['id_commentaire']:03d}R{reponse_data['id_commentaire']:02d}",
                    auteur=reponse_data['auteur'],
                    date_publication=reponse_data['date_publication'],
                    contenu=reponse_data['contenu'],
                    type=Commentaire.TYPE_REPONSE,
                    longueur_contenu=reponse_data['longueur_contenu'],
                    mots_contenu=reponse_data['mots_contenu'],
                    date_extraction=timezone.now(),
                )
        
        return article

    def extract_article_id(self, url):
        """Extrait l'ID de l'article depuis l'URL"""
        return url.split('=')[-1]

    def supprimer_url(self, request):
        """Supprime une URL de la liste"""
        url_id = request.POST.get('url_id')
        
        try:
            url_storage = URLStorage.objects.get(id=url_id)
            url_storage.delete()
            messages.success(request, "URL supprimée avec succès")
        except URLStorage.DoesNotExist:
            messages.error(request, "URL non trouvée")
        
        return redirect('Commentaires:home')


@method_decorator(csrf_exempt, name='dispatch')
class APIScrapingStatus(View):
    """API pour récupérer le statut du scraping en temps réel"""
    
    def get(self, request, *args, **kwargs):
        historique_id = request.GET.get('historique_id')
        
        try:
            historique = ScrapingHistory.objects.get(id=historique_id)
            
            return JsonResponse({
                'statut': historique.statut,
                'progression': historique.progression,
                'date_fin': historique.date_fin.isoformat() if historique.date_fin else None,
                'erreur': historique.erreur,
            })
        except ScrapingHistory.DoesNotExist:
            return JsonResponse({'erreur': 'Historique non trouvé'}, status=404)

    """Historique des scrapings"""
    EN_COURS = 'cours'
    TERMINE = 'termine'
    ERREUR = 'erreur'
    
    STATUT_CHOICES = [
        (EN_COURS, 'En cours'),
        (TERMINE, 'Terminé'),
        (ERREUR, 'Erreur'),
    ]
    
    urls_selectionnees = models.TextField()  # JSON des URLs
    resultats = models.TextField(blank=True)  # JSON des résultats
    statut = models.CharField(max_length=10, choices=STATUT_CHOICES, default=EN_COURS)
    progression = models.IntegerField(default=0)  # 0-100
    erreur = models.TextField(blank=True)
    date_lancement = models.DateTimeField(auto_now_add=True)
    date_fin = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-date_lancement']