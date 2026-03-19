from django.contrib import admin
from django.utils import timezone

from accounts.models import ApiToken


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "name",
        "is_active",
        "created_at",
        "expires_at",
        "last_used_at",
        "rotated_at",
    )
    list_filter = ("is_active", "created_at", "expires_at")
    search_fields = ("user__username", "name", "token")
    readonly_fields = ("created_at", "last_used_at", "rotated_at")
    actions = ["rotate_tokens"]

    def rotate_tokens(self, request, queryset):
        for token in queryset:
            token.token = ApiToken.generate()
            token.rotated_at = timezone.now()
            token.save(update_fields=["token", "rotated_at"])
        self.message_user(request, f"Rotated {queryset.count()} token(s).")

    rotate_tokens.short_description = "Rotate selected tokens"
