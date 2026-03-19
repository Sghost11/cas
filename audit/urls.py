from django.urls import path

from . import views

urlpatterns = [
    path("", views.AuditHomeView.as_view(), name="audit_home"),
    path("ai-dashboard/", views.AiAuthorizationDashboardView.as_view(), name="ai_dashboard"),
    path("change-requests/", views.ChangeRequestListView.as_view(), name="change_requests"),
    path(
        "change-requests/<int:pk>/approve/",
        views.ChangeRequestApproveView.as_view(),
        name="change_request_approve",
    ),
    path(
        "change-requests/<int:pk>/deploy/",
        views.ChangeRequestDeployView.as_view(),
        name="change_request_deploy",
    ),
    path(
        "change-requests/<int:pk>/ai-approve-deploy/",
        views.ChangeRequestAiApproveDeployView.as_view(),
        name="change_request_ai_approve_deploy",
    ),
    path(
        "change-requests/<int:pk>/ai-approve-deploy/envelope/",
        views.ChangeRequestAiApproveDeployEnvelopeView.as_view(),
        name="change_request_ai_approve_deploy_envelope",
    ),
    path(
        "change-requests/ai-approve-deploy/",
        views.ChangeRequestAiApproveDeployBatchView.as_view(),
        name="change_request_ai_approve_deploy_batch",
    ),
    path(
        "change-requests/ai-approve-deploy/async/",
        views.ChangeRequestAiApproveDeployBatchAsyncView.as_view(),
        name="change_request_ai_approve_deploy_batch_async",
    ),
    path(
        "change-requests/<int:pk>/results/",
        views.ChangeRequestResultsView.as_view(),
        name="change_request_results",
    ),
    path(
        "change-requests/<int:pk>/",
        views.ChangeRequestDetailView.as_view(),
        name="change_request_detail",
    ),
    path("tokens/revoke/", views.TokenRevokeView.as_view(), name="token_revoke"),
    path("tokens/rotate/", views.TokenRotateView.as_view(), name="token_rotate"),
    path("tokens/", views.TokenListView.as_view(), name="token_list"),
    path(
        "diff/<int:pk>/",
        views.ChangeRequestDiffView.as_view(),
        name="change_request_diff",
    ),
    path("jobs/<str:task_id>/", views.JobStatusView.as_view(), name="job_status"),
]
