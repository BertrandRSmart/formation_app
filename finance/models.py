# finance/models.py
from django.db import models

from trainings.models import MercureContract, MercureInvoice


class FinanceMercureContract(MercureContract):
    class Meta:
        proxy = True
        app_label = "finance"
        verbose_name = "Contrat d’application"
        verbose_name_plural = "Contrats d’application"


class FinanceMercureInvoice(MercureInvoice):
    class Meta:
        proxy = True
        app_label = "finance"
        verbose_name = "Facture"
        verbose_name_plural = "Factures"