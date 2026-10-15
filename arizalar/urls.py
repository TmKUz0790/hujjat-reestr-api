from django.urls import path

from . import views

urlpatterns = [
    path('arizalar', views.ArizalarView.as_view(), name='arizalar'),
    path('arizalar/<int:pk>', views.ArizaView.as_view(), name='ariza'),
    path('arizalar/<int:pk>/tasdiqlash', views.TasdiqlashView.as_view(), name='tasdiqlash'),
    path('arizalar/<int:pk>/qaytarish', views.QaytarishView.as_view(), name='qaytarish'),
    path('arizalar/<int:pk>/fayllar/<str:maydon>', views.FaylView.as_view(), name='fayl'),
    path('soato', views.SoatoView.as_view(), name='soato'),
]
