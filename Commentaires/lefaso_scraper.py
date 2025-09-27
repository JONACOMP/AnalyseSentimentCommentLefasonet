"""
Scraper de commentaires pour LeFaso.net
Auteur: Assistant AI
Date: 2024
Description: Ce script scrape les commentaires d'articles de LeFaso.net et les structure dans un DataFrame
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import json
from datetime import datetime
import re
import os
from typing import Dict, List, Optional, Any

class LefasoCommentScraper:
    """
    Classe principale pour scraper et structurer les commentaires de LeFaso.net
    """
    
    def __init__(self):
        """Initialise le scraper avec les paramètres de base"""
        self.session = requests.Session()
        self.setup_headers()
        self.base_url = "https://lefaso.net"
        self.dataframe = None
        
    def setup_headers(self):
        """Configure les en-têtes HTTP pour simuler un navigateur réel"""
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'fr-FR,fr;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
    
    def fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """
        Récupère le contenu HTML d'une page
        
        Args:
            url (str): URL de la page à scraper
            
        Returns:
            Optional[BeautifulSoup]: Objet BeautifulSoup ou None en cas d'erreur
        """
        try:
            print(f"📡 Récupération de la page: {url}")
            response = requests.get(url, headers=self.setup_headers())
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        except requests.RequestException as e:
            print(f"❌ Erreur lors de la récupération de la page: {e}")
            return None
    
    def extract_article_info(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """
        Extrait les informations principales de l'article
        
        Args:
            soup (BeautifulSoup): Objet BeautifulSoup de la page
            
        Returns:
            Dict: Dictionnaire contenant les métadonnées de l'article
        """
        article_info = {
            'titre': 'Non trouvé',
            'url': 'Non trouvé',
            'date_publication': 'Non trouvé',
            'categorie': 'Non trouvé',
            'date_scraping': datetime.now().isoformat()
        }
        
        try:
            # Titre de l'article
            title_elems = soup.find_all('h1', class_='entry-title')
            if len(title_elems) >= 2:
                article_info['titre'] = title_elems[1].get_text(strip=True)
            elif len(title_elems) == 1:
                article_info['titre'] = title_elems[0].get_text(strip=True)
            else:
                print("Aucun h1 avec class='entry-title' trouvé")
            
            # Date de publication
            for p in soup.find_all('p'):
                text = p.get_text()
                if 'Publié le' in text:
                    article_info['date_publication'] = text.replace('Publié le', '').strip()
                    break
            
            # Catégorie
            hierarchie = soup.find('div', id='hierarchie')
            if hierarchie:
                article_info['categorie'] = hierarchie.get_text(strip=True)
                
        except Exception as e:
            print(f"Erreur extraction infos article: {e}")
        
        return article_info
    
    def extract_comments_section(self, soup: BeautifulSoup) -> Optional[BeautifulSoup]:
        """
        Localise et retourne la section des commentaires
        
        Args:
            soup (BeautifulSoup): Objet BeautifulSoup de la page
            
        Returns:
            Optional[BeautifulSoup]: Section des commentaires ou None
        """
        # Essai direct (comme ton script qui marche)
        comments_section = soup.find("ul", id="navforum")
        if comments_section:
            print("✅ Section commentaires trouvée avec find(id='navforum')")
            return comments_section
        
        # Sélecteurs CSS de secours
        selectors = [
            'ul#navforum',
            '.forum',
            '#navforum',
            'ul[id*="forum"]',
            '.commentaires',
            '#commentaires'
        ]
        
        for selector in selectors:
            comments_section = soup.select_one(selector)
            if comments_section:
                print(f"✅ Section commentaires trouvée avec le sélecteur CSS: {selector}")
                return comments_section
        
        # Fallback: chercher par texte
        comment_headers = soup.find_all(['h2', 'h3', 'h4'], string=re.compile(r'commentaires|réactions', re.IGNORECASE))
        for header in comment_headers:
            section = header.find_next_sibling('ul')
            if section:
                print("✅ Section commentaires trouvée via en-tête")
                return section
        
        print("❌ Aucune section de commentaires trouvée")
        return None
    
    def parse_comment_author_date(self, text: str) -> tuple:
        """
        Parse le texte pour extraire l'auteur et la date
        
        Args:
            text (str): Texte contenant l'auteur et la date
            
        Returns:
            tuple: (auteur, date)
        """
        auteur, date = "Anonyme", "Date inconnue"
        
        try:
            # Plusieurs patterns possibles
            patterns = [
                (r'par\s+([^,]+),\s*(.+)', 1, 2),  # "par Auteur, Date"
                (r'De\s+([^,]+),\s*(.+)', 1, 2),   # "De Auteur, Date"
                (r'Posté par\s+([^,]+),\s*(.+)', 1, 2),  # "Posté par Auteur, Date"
                (r'(\w+)\s+-\s*(.+)', 1, 2),  # "Auteur - Date"
            ]
            
            for pattern, author_group, date_group in patterns:
                match = re.search(pattern, text)
                if match:
                    auteur = match.group(author_group).strip()
                    date = match.group(date_group).strip()
                    break
            else:
                # Fallback: simple split sur la première virgule
                if 'par' in text and ',' in text:
                    parts = text.split('par', 1)[1].split(',', 1)
                    auteur = parts[0].strip() if parts[0].strip() else "Anonyme"
                    date = parts[1].strip() if len(parts) > 1 else "Date inconnue"
                    
        except Exception as e:
            print(f"⚠️ Erreur parsing auteur/date: {e}")
            
        return auteur, date
    
    def extract_comment_content(self, comment_element) -> str:
        """
        Extrait le contenu textuel d'un commentaire
        
        Args:
            comment_element: Élément HTML du commentaire
            
        Returns:
            str: Contenu nettoyé du commentaire
        """
        content = ""
        
        # Sélecteurs prioritaires pour le contenu
        content_selectors = [
            '.ugccmt-commenttext',
            '.forum-texte',
            '.comment-text',
            '.comment-content',
            '.commentaire-texte'
        ]
        
        for selector in content_selectors:
            content_elem = comment_element.select_one(selector)
            if content_elem:
                content = content_elem.get_text(strip=True)
                if content and len(content) > 10:  # Vérifier que le contenu est significatif
                    break
        
        # Fallback: prendre le texte de div spécifiques ou de l'élément parent
        if not content:
            # Chercher des div avec du texte significatif
            text_elements = comment_element.find_all(['div', 'p'], string=True)
            for elem in text_elements:
                text = elem.get_text(strip=True)
                if len(text) > 20 and not any(keyword in text.lower() for keyword in ['par', 'répondre', 'date']):
                    content = text
                    break
        
        # Dernier fallback: texte de tout l'élément
        if not content:
            content = comment_element.get_text(strip=True)
        
        return self.clean_text(content)
    
    def extract_replies(self, comment_element) -> List[Dict[str, str]]:
        """
        Extrait les réponses à un commentaire
        
        Args:
            comment_element: Élément HTML du commentaire parent
            
        Returns:
            List[Dict]: Liste des réponses structurées
        """
        replies = []
        
        try:
            # Les réponses peuvent être dans différentes structures
            reply_containers = [
                comment_element.find('ul'),
                comment_element.find('div', class_=re.compile(r'reply|reponse')),
                comment_element.find_next_sibling('div', class_=re.compile(r'reply|reponse'))
            ]
            
            for container in reply_containers:
                if container:
                    reply_items = container.find_all('li') if container.name == 'ul' else [container]
                    
                    for i, reply_item in enumerate(reply_items, 1):
                        reply_data = self.parse_single_comment(reply_item, i, is_reply=True)
                        if reply_data and reply_data.get('contenu'):
                            replies.append(reply_data)
                    break  # Prendre le premier container valide
                        
        except Exception as e:
            print(f"⚠️ Erreur extraction réponses: {e}")
            
        return replies
    
    def parse_single_comment(self, comment_element, comment_id: int, is_reply: bool = False) -> Optional[Dict[str, Any]]:
        """
        Parse un commentaire individuel (ou une réponse)
        
        Args:
            comment_element: Élément HTML du commentaire
            comment_id (int): ID du commentaire
            is_reply (bool): Si c'est une réponse
            
        Returns:
            Optional[Dict]: Données structurées du commentaire
        """
        try:
            # Extraire l'en-tête (auteur et date)
            chapo_elem = comment_element.find('div', class_='forum-chapo')
            auteur, date = "Anonyme", "Date inconnue"
            
            if chapo_elem:
                auteur, date = self.parse_comment_author_date(chapo_elem.get_text(strip=True))
            else:
                # Fallback: chercher d'autres éléments d'en-tête
                header_selectors = ['.comment-author', '.author', '.user-name', '.comment-meta']
                for selector in header_selectors:
                    header_elem = comment_element.select_one(selector)
                    if header_elem:
                        auteur, date = self.parse_comment_author_date(header_elem.get_text(strip=True))
                        break
            
            # Extraire le contenu
            contenu = self.extract_comment_content(comment_element)
            
            # Filtrer les contenus non significatifs
            if not contenu or len(contenu) < 10:  # Augmenté le seuil minimum
                return None
            
            # Vérifier que ce n'est pas un élément d'interface (bouton, etc.)
            interface_keywords = ['répondre', 'reply', 'partager', 'share', 'like']
            if any(keyword in contenu.lower() for keyword in interface_keywords) and len(contenu) < 30:
                return None
            
            comment_data = {
                'id_commentaire': comment_id,
                'auteur': auteur,
                'date_publication': date,
                'contenu': contenu,
                'type': 'reponse' if is_reply else 'commentaire',
                'longueur_contenu': len(contenu),
                'mots_contenu': len(contenu.split()),
                'timestamp_extraction': datetime.now().isoformat()
            }
            
            return comment_data
            
        except Exception as e:
            print(f"⚠️ Erreur parsing commentaire {comment_id}: {e}")
            return None
    
    def clean_text(self, text: str) -> str:
        """
        Nettoie le texte des caractères indésirables
        
        Args:
            text (str): Texte à nettoyer
            
        Returns:
            str: Texte nettoyé
        """
        if not text:
            return ""
        
        # Supprimer les espaces multiples et les sauts de ligne excessifs
        text = re.sub(r'\s+', ' ', text)
        
        # Nettoyer les caractères spéciaux tout en conservant la ponctuation française
        text = re.sub(r'[^\w\sàâäéèêëîïôöùûüçÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ.,!?;:()\-&\'"]', '', text)
        
        # Nettoyer les URLs et emails
        text = re.sub(r'http\S+', '', text)  # URLs
        text = re.sub(r'\S+@\S+', '', text)  # Emails
        
        return text.strip()
    
    def scrape_article_comments(self, url: str) -> Dict[str, Any]:
        """
        Point d'entrée principal pour scraper les commentaires d'un article
        
        Args:
            url (str): URL de l'article à scraper
            
        Returns:
            Dict: Données complètes de l'article et ses commentaires
        """
        print(f"\n🎯 Début du scraping pour: {url}")
        
        # Récupérer la page
        soup = self.fetch_page(url)
        if not soup:
            return {'erreur': 'Impossible de récupérer la page', 'url': url}
        
        # Extraire les informations de l'article
        article_info = self.extract_article_info(soup)
        
        # Localiser la section des commentaires
        comments_section = self.extract_comments_section(soup)
        if not comments_section:
            article_info['commentaires'] = []
            article_info['statistiques'] = {
                'total_commentaires': 0, 
                'total_reponses': 0,
                'total_interventions': 0,
                'statut': 'Aucun commentaire trouvé'
            }
            return article_info
        
        # Extraire les commentaires principaux - avec sélecteurs plus flexibles
        commentaires_principaux = []
        
        # Essayer différents sélecteurs pour les commentaires
        comment_selectors = [
            'li.forum-fil',
            '.comment',
            '.commentaire',
            'li.comment',
            '.forum-message'
        ]
        
        comment_items = []
        for selector in comment_selectors:
            comment_items = comments_section.select(selector)
            if comment_items:
                print(f"✅ Commentaires trouvés avec le sélecteur: {selector}")
                break
        
        # Fallback: prendre tous les li dans la section
        if not comment_items:
            comment_items = comments_section.find_all('li')
        
        print(f"📊 {len(comment_items)} élément(s) de commentaire(s) trouvé(s)")
        
        for i, comment_item in enumerate(comment_items, 1):
            # Parser le commentaire principal
            comment_data = self.parse_single_comment(comment_item, i)
            if not comment_data:
                continue
            
            # Extraire les réponses
            reponses = self.extract_replies(comment_item)
            comment_data['reponses'] = reponses
            comment_data['nombre_reponses'] = len(reponses)
            
            commentaires_principaux.append(comment_data)
        
        # Compiler les statistiques
        total_reponses = sum(comment['nombre_reponses'] for comment in commentaires_principaux)
        
        article_info['url'] = url
        article_info['commentaires'] = commentaires_principaux
        article_info['statistiques'] = {
            'total_commentaires': len(commentaires_principaux),
            'total_reponses': total_reponses,
            'total_interventions': len(commentaires_principaux) + total_reponses,
            'statut': 'Succès' if commentaires_principaux else 'Aucun commentaire valide'
        }
        
        print(f"✅ Scraping terminé: {len(commentaires_principaux)} commentaires, {total_reponses} réponses")
        
        return article_info
    
    def create_dataframe(self, data: Dict[str, Any]) -> pd.DataFrame:
        """
        Crée un DataFrame pandas structuré à partir des données scrapées
        
        Args:
            data (Dict): Données scrapées
            
        Returns:
            pd.DataFrame: DataFrame structuré
        """
        rows = []
        
        # Vérifier si des commentaires existent
        if not data.get('commentaires'):
            print("⚠️ Aucun commentaire à structurer")
            return pd.DataFrame()
        
        for commentaire in data.get('commentaires', []):
            # ID unique pour l'article (basé sur l'URL)
            article_id = re.sub(r'[^\w]', '_', data.get('url', 'unknown'))[:50]
            
            # Ligne pour le commentaire principal
            row_comment = {
                'id_article': article_id,
                'titre_article': data.get('titre', ''),
                'url_article': data.get('url', ''),
                'date_publication_article': data.get('date_publication', ''),
                'categorie_article': data.get('categorie', ''),
                'date_scraping': data.get('date_scraping', ''),
                
                'id_commentaire': f"{article_id}_C{commentaire['id_commentaire']:03d}",
                'id_parent': None,
                'type': 'commentaire',
                'auteur': commentaire['auteur'],
                'date_publication': commentaire['date_publication'],
                'contenu': commentaire['contenu'],
                'longueur_contenu': commentaire['longueur_contenu'],
                'mots_contenu': commentaire['mots_contenu'],
                'nombre_reponses': commentaire.get('nombre_reponses', 0),
                'timestamp_extraction': commentaire.get('timestamp_extraction', '')
            }
            rows.append(row_comment)
            
            # Lignes pour les réponses
            for reponse in commentaire.get('reponses', []):
                row_reponse = {
                    'id_article': article_id,
                    'titre_article': data.get('titre', ''),
                    'url_article': data.get('url', ''),
                    'date_publication_article': data.get('date_publication', ''),
                    'categorie_article': data.get('categorie', ''),
                    'date_scraping': data.get('date_scraping', ''),
                    
                    'id_commentaire': f"{article_id}_C{commentaire['id_commentaire']:03d}R{reponse['id_commentaire']:02d}",
                    'id_parent': f"{article_id}_C{commentaire['id_commentaire']:03d}",
                    'type': 'reponse',
                    'auteur': reponse['auteur'],
                    'date_publication': reponse['date_publication'],
                    'contenu': reponse['contenu'],
                    'longueur_contenu': reponse['longueur_contenu'],
                    'mots_contenu': reponse['mots_contenu'],
                    'nombre_reponses': 0,
                    'timestamp_extraction': reponse.get('timestamp_extraction', '')
                }
                rows.append(row_reponse)
        
        self.dataframe = pd.DataFrame(rows)
        
        # Réorganiser les colonnes pour une meilleure lisibilité
        column_order = [
            'id_commentaire', 'id_parent', 'type', 'auteur', 'date_publication', 'contenu',
            'longueur_contenu', 'mots_contenu', 'nombre_reponses', 'timestamp_extraction',
            'id_article', 'titre_article', 'url_article', 'date_publication_article', 
            'categorie_article', 'date_scraping'
        ]
        
        # Garder seulement les colonnes existantes
        existing_columns = [col for col in column_order if col in self.dataframe.columns]
        self.dataframe = self.dataframe[existing_columns + 
                                       [col for col in self.dataframe.columns if col not in existing_columns]]
        
        return self.dataframe
    
    def save_to_excel(self, data: Dict[str, Any], filename: str = None):
        """
        Sauvegarde les données dans un fichier Excel
        
        Args:
            data (Dict): Données à sauvegarder
            filename (str): Nom du fichier (optionnel)
        """
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"lefaso_comments_{timestamp}.xlsx"
        
        # Créer le DataFrame si nécessaire
        if self.dataframe is None:
            self.create_dataframe(data)
        
        if self.dataframe.empty:
            print("❌ Aucune donnée à sauvegarder dans le fichier Excel")
            return
        
        try:
            with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                # Feuille principale avec tous les commentaires
                self.dataframe.to_excel(writer, sheet_name='Commentaires', index=False)
                
                # Feuille avec les statistiques
                stats_data = {
                    'Metric': list(data.get('statistiques', {}).keys()),
                    'Value': list(data.get('statistiques', {}).values())
                }
                pd.DataFrame(stats_data).to_excel(writer, sheet_name='Statistiques', index=False)
                
                # Feuille avec les infos de l'article
                article_info = {k: v for k, v in data.items() if k not in ['commentaires', 'statistiques', 'erreur']}
                pd.DataFrame([article_info]).to_excel(writer, sheet_name='Article', index=False)
                
                # Ajouter un onglet avec un aperçu des données
                preview_df = self.dataframe.head(10)[['auteur', 'type', 'date_publication', 'contenu']]
                preview_df.to_excel(writer, sheet_name='Aperçu', index=False)
            
            print(f"💾 Fichier Excel sauvegardé: {filename}")
            print(f"📊 Dimensions: {len(self.dataframe)} lignes × {len(self.dataframe.columns)} colonnes")
            
        except Exception as e:
            print(f"❌ Erreur sauvegarde Excel: {e}")
    
    def save_to_json(self, data: Dict[str, Any], filename: str = None):
        """
        Sauvegarde les données dans un fichier JSON
        
        Args:
            data (Dict): Données à sauvegarder
            filename (str): Nom du fichier (optionnel)
        """
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"lefaso_comments_{timestamp}.json"
        
        try:
            # Structure JSON complète
            output_data = {
                'metadata': {
                    'source': 'LeFaso.net',
                    'date_extraction': datetime.now().isoformat(),
                    'version': '1.0'
                },
                'article': {k: v for k, v in data.items() if k not in ['commentaires', 'statistiques']},
                'statistiques': data.get('statistiques', {}),
                'commentaires': data.get('commentaires', [])
            }
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2, default=str)
            
            print(f"💾 Fichier JSON sauvegardé: {filename}")
            
        except Exception as e:
            print(f"❌ Erreur sauvegarde JSON: {e}")
    
    def display_summary(self, data: Dict[str, Any]):
        """
        Affiche un résumé des données scrapées
        
        Args:
            data (Dict): Données à résumer
        """
        print("\n" + "="*80)
        print("📊 RÉSUMÉ DU SCRAPING")
        print("="*80)
        
        if 'erreur' in data:
            print(f"❌ Erreur: {data['erreur']}")
            return
        
        print(f"📰 Article: {data.get('titre', 'N/A')}")
        print(f"🔗 URL: {data.get('url', 'N/A')}")
        print(f"📅 Date publication: {data.get('date_publication', 'N/A')}")
        print(f"📂 Catégorie: {data.get('categorie', 'N/A')}")
        
        stats = data.get('statistiques', {})
        print(f"💬 Commentaires principaux: {stats.get('total_commentaires', 0)}")
        print(f"↩️ Réponses: {stats.get('total_reponses', 0)}")
        print(f"📈 Total interventions: {stats.get('total_interventions', 0)}")
        print(f"⏰ Date scraping: {data.get('date_scraping', 'N/A')}")
        print(f"📋 Statut: {stats.get('statut', 'N/A')}")
        
        # Aperçu des commentaires
        if data.get('commentaires'):
            print("\n👁️ APERÇU DES COMMENTAIRES:")
            print("-" * 40)
            for i, comment in enumerate(data['commentaires'][:3]):
                print(f"\n#{i+1} - {comment['auteur']} ({comment['date_publication']})")
                print(f"Contenu: {comment['contenu'][:100]}...")
                if comment.get('reponses'):
                    print(f"📨 {len(comment['reponses'])} réponse(s)")
        else:
            print("\nℹ️ Aucun commentaire à afficher")


def main():
    """
    Fonction principale - Point d'entrée du script
    """
    # Initialiser le scraper
    scraper = LefasoCommentScraper()
    
    # URL par défaut (peut être modifiée)
    url_defaut = "https://lefaso.net/spip.php?article111192"
    
    print("🚀 SCRAPER DE COMMENTAIRES LeFaso.net")
    print("="*50)
    
    # Demander l'URL à scraper
    try:
        url_choice = input(f"URL par défaut: {url_defaut}\nUtiliser cette URL? (o/n): ").strip().lower()
        
        if url_choice == 'n':
            url = input("Entrez l'URL complète de l'article LeFaso.net: ").strip()
        else:
            url = url_defaut
        
        if not url.startswith('http'):
            url = 'https://' + url
            
    except KeyboardInterrupt:
        print("\n❌ Opération annulée par l'utilisateur")
        return
    except Exception as e:
        print(f"❌ Erreur saisie URL: {e}")
        return
    
    # Scraper les données
    data = scraper.scrape_article_comments(url)
    
    if not data:
        print("❌ Aucune donnée récupérée")
        return
    
    # Afficher le résumé
    scraper.display_summary(data)
    
    # Créer le DataFrame
    df = scraper.create_dataframe(data)
    
    if df.empty:
        print("❌ DataFrame vide - aucune donnée à sauvegarder")
        return
    
    print(f"\n📋 DataFrame créé: {len(df)} lignes, {len(df.columns)} colonnes")
    
    # Sauvegarder les données
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    base_filename = f"lefaso_comments_{timestamp}"
    
    # Sauvegarde Excel
    scraper.save_to_excel(data, f"{base_filename}.xlsx")
    
    # Sauvegarde JSON
    scraper.save_to_json(data, f"{base_filename}.json")
    
    # Aperçu du DataFrame
    print(f"\n📊 Aperçu du DataFrame (5 premières lignes):")
    print(df[['auteur', 'type', 'date_publication', 'contenu']].head())
    
    # Statistiques supplémentaires
    print(f"\n📈 Statistiques supplémentaires:")
    print(f"• Auteurs uniques: {df['auteur'].nunique()}")
    print(f"• Longueur moyenne des commentaires: {df['longueur_contenu'].mean():.1f} caractères")
    print(f"• Mots moyens par commentaire: {df['mots_contenu'].mean():.1f} mots")
    
    print(f"\n✅ Script terminé avec succès!")


if __name__ == "__main__":
    main()