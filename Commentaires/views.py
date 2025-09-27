from django.shortcuts import render, redirect
from django.views import View
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.db import transaction
import pandas as pd
import json
import threading
import time
from django.db import IntegrityError, DataError
from django.core.exceptions import ValidationError
import hashlib

from .models import *
from .lefaso_scraper import LefasoCommentScraper

import re
import emoji
import spacy

from django.shortcuts import render, get_object_or_404
from django.db.models import Count, Avg, Q
from django.utils import timezone
from datetime import datetime, timedelta
import numpy as np
from collections import Counter
from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification
import torch
from typing import Dict, List, Any

nlp = spacy.load("fr_core_news_sm", disable=["parser", "ner"])


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
            print(request, "Cet article a déjà été scrapé précédemment")
        
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
                        article_sauvegarde = self.sauvegarder_dans_base(data)
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
        
        def clean_comment(text: str) -> str:
            """
            Nettoie et normalise un commentaire :
            - Conversion des emojis en texte lisible (:thumbs_up:)
            - Suppression des URLs, mentions et hashtags
            - Suppression des caractères spéciaux et chiffres inutiles
            - Réduction des espaces multiples
            - Lemmatisation (SpaCy) avec suppression des stopwords
            """
            if not isinstance(text, str) or not text.strip():
                return ""

            # 1. Convertir les emojis en texte
            text = emoji.demojize(text, delimiters=(" ", " "))

            # 2. Supprimer les URLs
            text = re.sub(r"http\S+|www\S+", " ", text)

            # 3. Supprimer les mentions et hashtags
            text = re.sub(r"[@#]\w+", " ", text)

            # 4. Supprimer les caractères spéciaux (on garde les lettres et accents)
            text = re.sub(r"[^a-zA-ZÀ-ÿ\s]", " ", text)

            # 5. Réduire les espaces multiples
            text = re.sub(r"\s+", " ", text).strip()

            # 6. Lemmatisation avec suppression des stopwords
            doc = nlp(text.lower())
            text_lem = " ".join(
                [token.lemma_ for token in doc if not token.is_punct and not token.is_space and not token.is_stop]
            )

            return text_lem
        
        # Vérification de base
        if not data or "statistiques" not in data:
            return None

        # Infos générales de l'article
        article_info = data
        commentaires_data = data.get("commentaires", [])
        stats = data.get("statistiques", {})
        # Créer ou mettre à jour l'article
        article, created = Article.objects.update_or_create(
            article_id=self.extract_article_id(article_info.get("url", "")),
            defaults={
                "titre": article_info.get("titre", ""),
                "url": article_info.get("url", ""),
                "date_publication": article_info.get("date_publication"),
                "categorie": article_info.get("categorie", ""),
                "date_scraping": timezone.now(),
                "nombre_commentaires": stats.get("total_commentaires", 0),
                "nombre_reponses": stats.get("total_reponses", 0),
            }
        )

        # Sauvegarder les commentaires principaux
        for comment_data in commentaires_data:
            
            contenu_brut = comment_data.get("contenu", "")
            contenu_propre = clean_comment(contenu_brut)
            try:
                commentaire = Commentaire.objects.create(
                    article=article,
                    commentaire_id=f"C{comment_data.get('id_commentaire', 0):03d}",
                    auteur=comment_data.get("auteur", "Anonyme"),
                    date_publication=comment_data.get("date_publication"),
                    contenu=comment_data.get("contenu", ""),
                    type=Commentaire.TYPE_COMMENTAIRE,
                    longueur_contenu=comment_data.get("longueur_contenu", 0),
                    mots_contenu=comment_data.get("mots_contenu", 0),
                    contenu_propre=contenu_propre,
                    longueur_contenu_propre=len(contenu_propre),
                    mots_contenu_propre=len(contenu_propre.split()),
                    date_extraction=timezone.now(),
                )
                print("✅ Commentaire créé :", commentaire)
            except Exception as e:
                print("❌ Erreur lors de la création du commentaire :", e)
                # import traceback
                # traceback.print_exc()
            # Sauvegarder les réponses associées
            for reponse_data in comment_data.get("reponses", []):
                
                contenu_brut = reponse_data.get("contenu", "")
                contenu_propre = clean_comment(contenu_brut)
                
                Commentaire.objects.create(
                    article=article,
                    parent=commentaire,
                    commentaire_id=f"C{comment_data.get('id_commentaire', 0):03d}R{reponse_data.get('id_commentaire', 0):02d}",
                    auteur=reponse_data.get("auteur", "Anonyme"),
                    date_publication=reponse_data.get("date_publication"),
                    contenu=reponse_data.get("contenu", ""),
                    type=Commentaire.TYPE_REPONSE,
                    longueur_contenu=reponse_data.get("longueur_contenu", 0),
                    mots_contenu=reponse_data.get("mots_contenu", 0),
                    contenu_propre=contenu_propre,
                    longueur_contenu_propre=len(contenu_propre),
                    mots_contenu_propre=len(contenu_propre.split()),
                    date_extraction=timezone.now(),
                )

        return article


    def extract_article_id(self, url):
        return hashlib.md5(url.encode("utf-8")).hexdigest()
    

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
        
        
class AnalyticsView(View):
    """Vue principale pour le tableau de bord analytics"""
    
    def __init__(self):
        super().__init__()
        # Initialiser le pipeline BERT pour l'analyse des sentiments
        self.sentiment_analyzer = None
        self.initialize_sentiment_analyzer()
    
    def initialize_sentiment_analyzer(self):
        """Initialise le modèle BERT pour l'analyse des sentiments"""
        try:
            # Modèle BERT pré-entraîné pour l'analyse de sentiments en français
            model_name = "tblard/tf-allocine"  # Modèle BERT pour sentiments en français
            self.sentiment_analyzer = pipeline(
                "sentiment-analysis",
                model=model_name,
                tokenizer=model_name,
                framework="pt"
            )
            print("Modèle BERT pour l'analyse des sentiments initialisé")
        except Exception as e:
            print(f"Erreur initialisation BERT: {e}")
            # Fallback vers un modèle plus simple
            try:
                self.sentiment_analyzer = pipeline("sentiment-analysis")
                print("Modèle de fallback initialisé")
            except Exception as e2:
                print(f"Erreur fallback: {e2}")
                self.sentiment_analyzer = None
    
    def get_sentiment_bert(self, text: str) -> Dict[str, Any]:
        """Analyse le sentiment d'un texte avec BERT"""
        if not self.sentiment_analyzer or not text:
            return {'label': 'NEUTRAL', 'score': 0.5}
        
        try:
            # Limiter la longueur du texte pour BERT
            if len(text) > 512:
                text = text[:512]
            
            result = self.sentiment_analyzer(text)[0]

            # Adapter les labels au modèle français
            label_map = {
                'positive': 'POSITIF',
                'negative': 'NEGATIF', 
                'neutral': 'NEUTRE',
                'POS': 'POSITIF',
                'NEG': 'NEGATIF',
                'NEU': 'NEUTRE'
            }
            
            label = label_map.get(result['label'], result['label'].upper())
            score = result['score']
            
            return {'label': label, 'score': score}
            
        except Exception as e:
            print(f"Erreur analyse sentiment: {e}")
            return {'label': 'NEUTRAL', 'score': 0.5}
    
    def get_sentiment_score(self, label: str, score: float) -> float:
        """Convertit le label de sentiment en score numérique (-1 à 1)"""
        sentiment_map = {
            'POSITIF': score,
            'NEGATIF': -score,
            'NEUTRE': 0.0
        }
        return sentiment_map.get(label.upper(), 0.0)
    
    def analyze_article_sentiments(self, article: Article) -> Dict[str, Any]:
        """Analyse les sentiments de tous les commentaires d'un article"""
        commentaires = article.commentaires.all()
        
        if not commentaires:
            return {
                'positif': 0,
                'negatif': 0,
                'neutre': 100,
                'moyen': 0.5,
                'total': 0
            }
        
        sentiments = []
        scores = []
        
        for commentaire in commentaires:
            text = commentaire.contenu_propre if commentaire.contenu_propre else commentaire.contenu
            sentiment = self.get_sentiment_bert(text)
            
            sentiments.append(sentiment['label'])
            score = self.get_sentiment_score(sentiment['label'], sentiment['score'])
            scores.append(score)
        
        # Calculer les pourcentages
        total = len(sentiments)

        positif = (sentiments.count('POSITIVE') / total) * 100
        negatif = (sentiments.count('NEGATIVE') / total) * 100
        neutre = (sentiments.count('NEUTRAL') / total) * 100

        # Score moyen (-1 à 1 converti en 0-100)
        score_moyen = ((np.mean(scores) + 1) / 2) * 100 if scores else 50

        return {
            'positif': round(positif, 1),
            'negatif': round(negatif, 1),
            'neutre': round(neutre, 1),
            'moyen': round(score_moyen, 1),
            'total': total
        }
    
    def get_word_frequency(self, articles=None, limit=50) -> List[tuple]:
        """Extrait les mots les plus fréquents des commentaires"""
        if articles is None:
            articles = Article.objects.all()
        
        all_text = ""
        for article in articles:
            for commentaire in article.commentaires.all():
                text = commentaire.contenu_propre if commentaire.contenu_propre else commentaire.contenu
                all_text += " " + text.lower()
        
        # Nettoyer et tokenizer le texte
        words = re.findall(r'\b[a-zàâçéèêëîïôûùüÿñæœ]{3,}\b', all_text)
        
        # Filtrer les stopwords français
        stopwords_fr = {
            'les', 'des', 'que', 'est', 'dans', 'pour', 'sur', 'avec', 'par', 'mais', 'comme',
            'plus', 'tout', 'cest', 'fait', 'être', 'avoir', 'faire', 'dire', 'voir', 'savoir',
            'vouloir', 'pouvoir', 'devoir', 'aller', 'venir', 'ceci', 'cela', 'cette', 'ces',
            'dun', 'dune', 'quil', 'quils', 'mais', 'donc', 'or', 'ni', 'car', 'à', 'au', 'aux',
            'du', 'de', 'la', 'le', 'les', 'un', 'une', 'et', 'ou', 'où', 'qui', 'quoi', 'quand'
        }
        
        filtered_words = [word for word in words if word not in stopwords_fr]
        word_freq = Counter(filtered_words)
        
        # return word_freq.most_common(limit)
        return [[word, freq] for word, freq in word_freq.most_common(limit)]
    
    def get_activity_timeline(self, days=30) -> Dict[str, List]:
        """Génère les données d'activité par date"""
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        # Compter les commentaires par date
        activity_data = (
            Commentaire.objects
            .filter(date_extraction__gte=start_date)
            .extra({'date': "DATE(date_extraction)"})
            .values('date')
            .annotate(count=Count('id'))
            .order_by('date')
        )
        
        # Créer un DataFrame pour gérer les dates manquantes
        date_range = pd.date_range(start=start_date.date(), end=end_date.date())
        df = pd.DataFrame(date_range, columns=['date'])
        df['date_str'] = df['date'].dt.strftime('%Y-%m-%d')
        
        # Fusionner avec les données réelles
        # activity_dict = {item['date'].strftime('%Y-%m-%d'): item['count'] for item in activity_data}
        # df['count'] = df['date_str'].map(activity_dict).fillna(0)
        activity_dict = {item['date']: item['count'] for item in activity_data}
        df['count'] = df['date_str'].map(activity_dict).fillna(0)
    
        return {
            'labels': df['date_str'].tolist(),
            'data': df['count'].astype(int).tolist()
        }
    
    def get_top_authors(self, limit=10) -> Dict[str, List]:
        """Retourne les auteurs les plus actifs"""
        authors = (
            Commentaire.objects
            .values('auteur')
            .annotate(count=Count('id'))
            .order_by('-count')[:limit]
        )
        
        return {
            'labels': [author['auteur'] for author in authors],
            'data': [author['count'] for author in authors]
        }
    
    def calculate_engagement_rate(self, article: Article) -> float:
        """Calcule le taux d'engagement d'un article"""
        total_comments = article.nombre_commentaires + article.nombre_reponses
        
        # Facteurs d'engagement (à adapter selon vos métriques)
        length_factor = min(article.commentaires.aggregate(avg_len=Avg('longueur_contenu'))['avg_len'] or 0 / 100, 1)
        response_factor = min(article.nombre_reponses / max(article.nombre_commentaires, 1), 1)
        
        # Score d'engagement composite
        engagement = (length_factor * 0.4 + response_factor * 0.6) * 100
        
        return round(min(engagement, 100), 1)
    
    def get(self, request, *args, **kwargs):
        """Affiche le tableau de bord analytics"""
        
        # Récupérer tous les articles
        articles = Article.objects.all().prefetch_related('commentaires')
        
        # Statistiques globales
        total_articles = articles.count()
        total_commentaires = Commentaire.objects.count()
        auteurs_uniques = Commentaire.objects.values('auteur').distinct().count()
        
        # Analyse des sentiments globaux
        sentiment_global = self.analyze_article_sentiments_global(articles)
        
        # Données pour les graphiques
        activite_par_date = self.get_activity_timeline()
        top_auteurs = self.get_top_authors()
        mots_frequents = self.get_word_frequency()
        
        # Préparer les données pour chaque article
        articles_data = []
        for article in articles:
            sentiments = self.analyze_article_sentiments(article)
            taux_engagement = self.calculate_engagement_rate(article)
            mots_cles = [word for word, freq in self.get_word_frequency([article], 10)]
            
            articles_data.append({
                'id': article.id,
                'article_id': article.article_id,
                'titre': article.titre,
                'url': article.url,
                'date_publication': article.date_publication,
                'categorie': article.categorie,
                'nombre_commentaires': article.nombre_commentaires,
                'nombre_reponses': article.nombre_reponses,
                'taux_engagement': taux_engagement,
                'sentiment_moyen': sentiments['moyen'],
                'mots_cles': mots_cles,
                'sentiments': sentiments
            })
        print(json.dumps(activite_par_date))
        print(json.dumps(top_auteurs))
        context = {
            # Statistiques globales
            'total_articles': total_articles,
            'total_commentaires': total_commentaires,
            'auteurs_uniques': auteurs_uniques,
            'taux_engagement': self.calculate_global_engagement_rate(articles),
            
            # Analyse des sentiments
            'sentiment_positif': sentiment_global['positif'],
            'sentiment_negatif': sentiment_global['negatif'],
            'sentiment_neutre': sentiment_global['neutre'],
            
            # Données pour les graphiques
            'activite_par_date': json.dumps(activite_par_date),
            'top_auteurs': json.dumps(top_auteurs),
            'mots_frequents': json.dumps([list(item) for item in mots_frequents]),
            
            # Articles avec analytics
            'articles': articles_data,
        }
        
        return render(request, 'Commentaires/analytics.html', context)
    
    def analyze_article_sentiments_global(self, articles) -> Dict[str, float]:
        """Analyse les sentiments sur tous les articles"""
        all_sentiments = []
        
        for article in articles:
            sentiments = self.analyze_article_sentiments(article)
            all_sentiments.append(sentiments)
        
        if not all_sentiments:
            return {'positif': 0, 'negatif': 0, 'neutre': 100}
        
        # Moyenne pondérée par le nombre de commentaires
        total_comments = sum(sentiment['total'] for sentiment in all_sentiments)
        
        if total_comments == 0:
            return {'positif': 0, 'negatif': 0, 'neutre': 100}
        
        positif = sum(sentiment['positif'] * sentiment['total'] for sentiment in all_sentiments) / total_comments
        negatif = sum(sentiment['negatif'] * sentiment['total'] for sentiment in all_sentiments) / total_comments
        neutre = sum(sentiment['neutre'] * sentiment['total'] for sentiment in all_sentiments) / total_comments
        
        return {
            'positif': round(positif, 1),
            'negatif': round(negatif, 1),
            'neutre': round(neutre, 1)
        }
    
    def calculate_global_engagement_rate(self, articles) -> float:
        """Calcule le taux d'engagement global"""
        if not articles:
            return 0.0
        
        total_engagement = sum(self.calculate_engagement_rate(article) for article in articles)
        return round(total_engagement / len(articles), 1)


class ArticleDetailAPI(View):
    """API pour les détails d'un article spécifique"""
    
    def get(self, request, article_id):
        article = get_object_or_404(Article, id=article_id)
        analytics_view = AnalyticsView()
        
        sentiments = analytics_view.analyze_article_sentiments(article)
        taux_engagement = analytics_view.calculate_engagement_rate(article)
        
        data = {
            'id': article.id,
            'article_id': article.article_id,
            'titre': article.titre,
            'url': article.url,
            'date_publication': article.date_publication,
            'categorie': article.categorie,
            'nombre_commentaires': article.nombre_commentaires,
            'nombre_reponses': article.nombre_reponses,
            'taux_engagement': taux_engagement,
            'sentiment_moyen': sentiments['moyen'],
            'tendance_sentiment': self.get_sentiment_trend(sentiments),
            'date_scraping': article.date_scraping.strftime('%Y-%m-%d %H:%M'),
        }
        
        return JsonResponse(data)
    
    def get_sentiment_trend(self, sentiments: Dict[str, float]) -> str:
        """Détermine la tendance des sentiments"""
        if sentiments['positif'] > sentiments['negatif'] + 10:
            return "Positive"
        elif sentiments['negatif'] > sentiments['positif'] + 10:
            return "Négative"
        else:
            return "Neutre"


class AnalyzeArticleAPI(View):
    """API pour lancer une analyse approfondie d'un article"""
    
    def post(self, request, article_id):
        article = get_object_or_404(Article, id=article_id)
        analytics_view = AnalyticsView()
        
        try:
            # Analyse des sentiments détaillée
            sentiments = analytics_view.analyze_article_sentiments(article)
            
            # Analyse des mots-clés
            mots_cles = analytics_view.get_word_frequency([article], 20)
            
            # Statistiques avancées
            stats = self.get_advanced_stats(article)
            
            return JsonResponse({
                'status': 'success',
                'article_id': article.article_id,
                'sentiments': sentiments,
                'mots_cles': mots_cles,
                'stats': stats,
                'timestamp': timezone.now().isoformat()
            })
            
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=500)
    
    def get_advanced_stats(self, article: Article) -> Dict[str, Any]:
        """Calcule des statistiques avancées pour un article"""
        commentaires = article.commentaires.all()
        
        if not commentaires:
            return {}
        
        # Longueur moyenne des commentaires
        avg_length = commentaires.aggregate(avg_len=Avg('longueur_contenu'))['avg_len'] or 0
        
        # Distribution des auteurs
        author_dist = commentaires.values('auteur').annotate(count=Count('id')).order_by('-count')
        
        # Heure de publication la plus active
        hours = [c.date_extraction.hour for c in commentaires if c.date_extraction]
        peak_hour = Counter(hours).most_common(1)[0][0] if hours else 0
        
        return {
            'longueur_moyenne': round(avg_length, 1),
            'auteurs_actifs': len(author_dist),
            'auteur_principal': author_dist[0]['auteur'] if author_dist else 'Aucun',
            'heure_peak': peak_hour,
            'diversite_auteurs': len(author_dist) / len(commentaires) if commentaires else 0
        }


class ExportArticleAPI(View):
    """API pour exporter les données d'un article"""
    
    def get(self, request, article_id):
        article = get_object_or_404(Article, id=article_id)
        
        # Créer un DataFrame avec les données
        data = []
        for commentaire in article.commentaires.all():
            data.append({
                'Auteur': commentaire.auteur,
                'Date': commentaire.date_publication,
                'Contenu': commentaire.contenu,
                'Type': commentaire.type,
                'Longueur': commentaire.longueur_contenu,
                'Mots': commentaire.mots_contenu
            })
        
        df = pd.DataFrame(data)
        
        # Créer une réponse Excel
        response = HttpResponse(content_type='application/vnd.ms-excel')
        response['Content-Disposition'] = f'attachment; filename="article_{article.article_id}.xlsx"'
        
        with pd.ExcelWriter(response, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Commentaires', index=False)
            
            # Ajouter un onglet avec les statistiques
            stats_df = pd.DataFrame([{
                'Titre': article.titre,
                'URL': article.url,
                'Date Publication': article.date_publication,
                'Commentaires': article.nombre_commentaires,
                'Réponses': article.nombre_reponses,
                'Total Interventions': article.total_interventions()
            }])
            stats_df.to_excel(writer, sheet_name='Statistiques', index=False)
        
        return response


class WordCloudAPI(View):
    """API pour générer un nuage de mots spécifique"""
    
    def get(self, request, article_id=None):
        analytics_view = AnalyticsView()
        
        if article_id:
            article = get_object_or_404(Article, id=article_id)
            mots_frequents = analytics_view.get_word_frequency([article])
            title = f"Nuage de mots - {article.titre[:30]}..."
        else:
            mots_frequents = analytics_view.get_word_frequency()
            title = "Nuage de mots global"
        
        # Formater pour WordCloud2
        wordcloud_data = [[word, freq] for word, freq in mots_frequents]
        
        return JsonResponse({
            'title': title,
            'data': wordcloud_data
        })


