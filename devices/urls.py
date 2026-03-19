from django.urls import path

from . import views

urlpatterns = [
    path("ui/ops/", views.DeviceOpsUiView.as_view(), name="device_ops_ui"),
    path("db/", views.DeviceDbListView.as_view(), name="device_db_list"),
    path("<int:pk>/", views.DeviceDetailView.as_view(), name="device_detail"),
    path("<int:pk>/sync/", views.DeviceSyncView.as_view(), name="device_sync"),
    path("<int:pk>/ports/", views.DevicePortsView.as_view(), name="device_ports"),
    path("<int:pk>/validate/", views.DeviceValidateView.as_view(), name="device_validate"),
    path("import/", views.ImportCLIView.as_view(), name="device_import"),
]
