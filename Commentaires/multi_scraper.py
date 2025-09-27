import pandas as pd
from lefaso_scraper import LefasoCommentScraper
from datetime import datetime

def scraper_multiple_urls(urls):
    """
    Scrape plusieurs URLs et combine les résultats
    """
    scraper = LefasoCommentScraper()
    all_data = []
    
    for i, url in enumerate(urls, 1):
        print(f"\n🔍 Processing URL {i}/{len(urls)}: {url}")
        
        data = scraper.scrape_article_comments(url)
        if data and data.get('commentaires'):
            all_data.append(data)
    
    # Combiner tous les DataFrames
    combined_df = pd.DataFrame()
    for data in all_data:
        df = scraper.create_dataframe(data)
        combined_df = pd.concat([combined_df, df], ignore_index=True)
    
    # Sauvegarder le résultat combiné
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    combined_df.to_excel(f"lefaso_comments_combined_{timestamp}.xlsx", index=False)
    combined_df.to_json(f"lefaso_comments_combined_{timestamp}.json", orient='records', force_ascii=False)
    
    print(f"✅ {len(all_data)} articles scrapés, {len(combined_df)} commentaires au total")
    return combined_df

# Exemple d'utilisation
if __name__ == "__main__":
    urls = [
        "https://lefaso.net/spip.php?article137593",
        "https://lefaso.net/spip.php?article124600",
        "https://lefaso.net/spip.php?article111192",
        "https://lefaso.net/spip.php?article119046",
        "https://lefaso.net/spip.php?article122867",
        "https://lefaso.net/spip.php?article133172",
        "https://lefaso.net/spip.php?article137090",
        "https://lefaso.net/spip.php?article133365",
        "https://lefaso.net/spip.php?article137611",
        "https://lefaso.net/spip.php?article116538",
        "https://lefaso.net/spip.php?article134992",
    ]
    
    df = scraper_multiple_urls(urls)