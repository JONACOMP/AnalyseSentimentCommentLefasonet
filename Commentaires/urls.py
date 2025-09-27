from django.urls import path
from .views import *
app_name = "Commentaires"

urlpatterns = [
    path('', Home.as_view(), name='home'),
    path('analytics/', AnalyticsView.as_view(), name='analytics'),
    path('api/articles/<int:article_id>/', ArticleDetailAPI.as_view(), name='article_detail_api'),
    path('api/articles/<int:article_id>/analyze/', AnalyzeArticleAPI.as_view(), name='analyze_article'),
    path('api/articles/<int:article_id>/export/', ExportArticleAPI.as_view(), name='export_article'),
    path('api/wordcloud/', WordCloudAPI.as_view(), name='wordcloud_global'),
    path('api/wordcloud/<int:article_id>/', WordCloudAPI.as_view(), name='wordcloud_article'),
]