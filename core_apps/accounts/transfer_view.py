from dateutil import parser
from decimal import Decimal
from typing import Any

from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from django.utils import timezone
from loguru import logger
from rest_framework import generics, status
from rest_framework.filters import OrderingFilter
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core_apps.common.renderers import GenericJSONRenderer
from core_apps.user_auth.utils import generate_otp
from .emails import send_tranfer_otp_email, send_transfer_email
from .models import BankAccount, Transaction
from .pagination import StandardResultsSetPagination
from .serialiers import (
    TransactionSerializer,
    SecurityQuestionSerializer,
    OTPVerificationSerializer,
)
from .tasks import generate_transaction_pdf


class InitiateTransferView(generics.CreateAPIView):
    serializer_class = TransactionSerializer
    renderer_classes = [GenericJSONRenderer]
    object_label = "initiate_transfer"

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        data = request.data.copy()
        data["transaction_type"] = Transaction.TransactionType.TRANSFER
        sender_account_number = data.get("sender_account")
        receiver_account_number = data.get("receiver_account")

        try:
            sender_account = BankAccount.objects.get(
                account_number=sender_account_number, user=request.user
            )

            if not (sender_account.fully_activated and sender_account.kyc_verified):
                return Response(
                    {
                        "error": "This account is not fully activated. Please complete the "
                        "verification process by visiting any of our local bank branches"
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        except BankAccount.DoesNotExist:
            return Response(
                {
                    "error": "Sender account number not found or you're "
                    "not authorized to use this account"
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = self.get_serializer(data=data)
        if serializer.is_valid():
            request.session["transfer_data"] = {
                "sender_account": sender_account_number,
                "receiver_account": receiver_account_number,
                "amount": str(serializer.validated_data["amount"]),
                "description": serializer.validated_data.get("description", ""),
            }

            return Response(
                {
                    "message": "Please answer the security question to proceed with the transfer",
                    "next_step": "verify_security_question",
                },
                status=status.HTTP_201_CREATED,
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class VerifySecurityQuestionView(generics.CreateAPIView):
    serializer_class = SecurityQuestionSerializer
    renderer_classes = [GenericJSONRenderer]
    object_label = "verify_security_question"

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(
            data=request.data, context={"request": request}
        )

        if serializer.is_valid():
            otp = generate_otp()
            request.user.set_otp(otp)
            send_tranfer_otp_email(request.user.email, otp)
            return Response(
                {
                    "message": "Security question verified. An OTP has been sent to your email",
                    "next_step": "verify_otp",
                },
                status=status.HTTP_200_OK,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class VerifyOTPView(generics.CreateAPIView):
    serializer_class = OTPVerificationSerializer
    renderer_classes = [GenericJSONRenderer]
    object_label = "otp_verify"

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(
            data=request.data, context={"request": request}
        )
        if serializer.is_valid():
            return self.process_transfer(request)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def process_transfer(self, request: Request) -> Response:
        transfer_data = request.session.get("transfer_data")
        if not transfer_data:
            return Response(
                {
                    "error": "Transfer data not found. Please start the process again",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            sender_account = BankAccount.objects.get(
                account_number=transfer_data["sender_account"]
            )
            receiver_account = BankAccount.objects.get(
                account_number=transfer_data["receiver_account"]
            )
        except BankAccount.DoesNotExist:
            return Response(
                {"error": "One or both accounts not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        amount = Decimal(transfer_data["amount"])
        if sender_account.account_balance < amount:
            return Response(
                {"error": "Insufficient funds for transfer"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sender_account.account_balance -= amount
        receiver_account.account_balance += amount

        sender_account.save()
        receiver_account.save()

        transfer_transaction = Transaction.objects.create(
            user=request.user,
            amount=amount,
            description=transfer_data["description"],
            sender=request.user,
            receiver=receiver_account.user,
            sender_account=sender_account,
            receiver_account=receiver_account,
            status=Transaction.TransactionStatus.COMPLETED,
            transaction_type=Transaction.TransactionType.TRANSFER,
        )

        del request.session["transfer_data"]

        send_transfer_email(
            sender_name=sender_account.user.full_name,
            sender_email=sender_account.user.email,
            receiver_name=receiver_account.user.full_name,
            receiver_email=receiver_account.user.email,
            amount=amount,
            currency=sender_account.currency,
            sender_new_balance=sender_account.account_balance,
            receiver_new_balance=receiver_account.account_balance,
            sender_account_number=sender_account.account_number,
            receiver_account_number=receiver_account.account_number,
        )
        logger.info(
            f"Transfer of {amount} made from {sender_account.account_number} "
            "to {receiver_account.account_number}"
        )

        return Response(
            TransactionSerializer(transfer_transaction).data,
            status=status.HTTP_201_CREATED,
        )


class TransactionListAPIView(generics.ListAPIView):
    serializer_class = TransactionSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    ordering_fields = ["created_at", "amount"]
    ordering = ["-created_at"]

    def get_queryset(self):
        user = self.request.user
        query_set = Transaction.objects.filter(Q(sender=user) | Q(receiver=user))
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")

        account_number = self.request.query_params.get("account_number")

        if start_date:
            try:
                start_date = parser.parse(start_date)
                query_set = query_set.filter(Q(created_at__gte=start_date))
            except ValueError:
                pass

        if end_date:
            try:
                end_date = parser.parse(end_date)
                query_set = query_set.filter(Q(created_at__lte=end_date))
            except ValueError:
                pass

        if account_number:
            try:
                account = BankAccount.objects.get(
                    account_number=account_number, user=user
                )
                query_set = query_set.filter(
                    Q(sender_account=account) | Q(receiver_account=account)
                )
            except BankAccount.DoesNotExist:
                query_set = Transaction.objects.none()

        return query_set

    def list(self, request, *args, **kwargs) -> Response:
        response = super().list(request, *args, **kwargs)

        account_number = self.request.query_params.get("account_number")
        if account_number:
            logger.info(
                f"User {request.user.email} successfully retrieved transactions "
                "for account {account_number}"
            )
        else:
            logger.info(
                f"User {request.user.email} successfully retrieved transactions (all accounts)"
            )

        return response


class TransactionPDFView(APIView):
    renderer_classes = [GenericJSONRenderer]
    object_label = "transaction_pdf"

    def post(self, request) -> Response:
        user = request.user
        start_date = request.data.get("start_date") or request.query_params.get(
            "start_date"
        )
        end_ate = request.data.get("end_ate") or request.query_params.get("end_ate")
        account_number = request.data.get("account_number") or request.query_params.get(
            "account_number"
        )

        if not end_ate:
            end_ate = timezone.now().date().isoformat()

        if not start_date:
            start_date = (
                (parser.parse(end_ate) - timezone.timedelta(days=30)).date().isoformat()
            )

        try:
            start_date = parser.parse(start_date).date().isoformat()
            end_ate = parser.parse(end_ate).date().isoformat()
        except ValueError as e:
            return Response(
                {"error": f"Invalid date format: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        generate_transaction_pdf(user.id, start_date, end_ate, account_number)

        return Response(
            {
                "message": "Your transaction history PDF is being generated and will be sent "
                "to your email shortly",
                "email": user.email
            },
            status=status.HTTP_202_ACCEPTED
        )
