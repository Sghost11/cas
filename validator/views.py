from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views import View


class ValidatorHomeView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        return JsonResponse({"status": "ok", "message": "validator placeholder"})
