# finance/admin.py
from django.contrib import admin
from .models import FinanceMercureContract, FinanceMercureInvoice


@admin.register(FinanceMercureContract)
class FinanceMercureContractAdmin(admin.ModelAdmin):
    list_display = ("reference", "session", "trainer", "status", "sent_date", "signed_date", "updated_at")
    list_filter = ("status", "trainer")
    search_fields = ("reference", "session__reference", "session__client__name", "trainer__first_name", "trainer__last_name", "trainer__email")
    ordering = ("-updated_at",)


@admin.register(FinanceMercureInvoice)
class FinanceMercureInvoiceAdmin(admin.ModelAdmin):
    list_display = ("reference", "session", "trainer", "amount_ht", "status", "received_date", "paid_date", "updated_at")
    list_filter = ("status", "trainer")
    search_fields = ("reference", "session__reference", "session__client__name", "trainer__first_name", "trainer__last_name", "trainer__email")
    ordering = ("-updated_at",)