from django.urls import path

from .views import (
    create_order,
    writer_orders,
    writer_order_detail,
    assign_writer,
    download_submission,
    client_order_action,
    staff_order_action,
)


urlpatterns = [

    path(
        "create/",
        create_order,
        name="create_order"
    ),

    path(
        "writer/",
        writer_orders,
        name="writer_orders"
    ),

    path(
        "writer/order/<int:order_id>/",
        writer_order_detail,
        name="writer_order_detail"
    ),

    path(
        "submission/<int:submission_id>/download/",
        download_submission,
        name="download_submission"
    ),

    path(
        "order/<int:order_id>/client-action/",
        client_order_action,
        name="client_order_action"
    ),

    path(
        "admin/order/<int:order_id>/action/",
        staff_order_action,
        name="staff_order_action"
    ),

    path(
        "admin/order/<int:order_id>/assign/",
        assign_writer,
        name="assign_writer"
    ),

]