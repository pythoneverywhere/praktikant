from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, StringConstraints, model_validator

# Общие ограничения длины входных полей (защита от мусора/DoS и ошибок БД на длинных строках).
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Phone = Annotated[str, StringConstraints(max_length=32)]
Identifier = Annotated[str, StringConstraints(max_length=254)]
Password = Annotated[str, Field(min_length=8, max_length=128)]
AnyPassword = Annotated[str, Field(max_length=128)]
Token = Annotated[str, StringConstraints(max_length=128)]
Code = Annotated[str, StringConstraints(max_length=16)]
Email = Annotated[EmailStr, Field(max_length=254)]


class RegisterIn(BaseModel):
    name: Name
    email: Email
    phone: Phone
    password: Password
    termsAccepted: bool


class LoginIn(BaseModel):
    identifier: Identifier
    password: AnyPassword


class StepUpVerifyIn(BaseModel):
    stepUpToken: Token
    emailCode: Code


class EmailVerifyRequestIn(BaseModel):
    email: Identifier | None = None
    identifier: Identifier | None = None


class EmailVerifyConfirmIn(BaseModel):
    token: Token | None = None
    code: Code | None = None
    email: Identifier | None = None
    identifier: Identifier | None = None


class PasswordResetRequestIn(BaseModel):
    identifier: Identifier


class PasswordResetConfirmIn(BaseModel):
    token: Token
    newPassword: Password


class PasswordChangeIn(BaseModel):
    currentPassword: AnyPassword
    newPassword: Password
    stepUpToken: Token | None = None
    emailCode: Code | None = None


class ProfileUpdateIn(BaseModel):
    name: Name
    email: Email
    phone: Phone
    stepUpToken: Token | None = None
    emailCode: Code | None = None


class StepUpStartIn(BaseModel):
    purpose: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    # Для purpose=profile_change: новый email, на который нужно отправить код.
    newEmail: Email | None = None


class ApplicationCreateIn(BaseModel):
    tariff: Annotated[str, StringConstraints(max_length=100)]
    socials: Annotated[str, StringConstraints(max_length=1000)]
    startDate: Annotated[str, StringConstraints(max_length=32)] | None = None
    endDate: Annotated[str, StringConstraints(max_length=32)] | None = None
    months: Annotated[str, StringConstraints(max_length=32)] | int | None = None
    promoCode: Annotated[str, StringConstraints(max_length=32)] | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_payload(cls, data):
        if not isinstance(data, dict):
            return data
        raw = dict(data)
        start = (raw.get("startDate") or raw.get("start_date") or "").strip()
        end = (raw.get("endDate") or raw.get("end_date") or "").strip()
        if not start and not end:
            # Legacy cached auth.js (old signature) could send:
            # months=<startDate>, promoCode=<endDate>.
            maybe_start = str(raw.get("months") or "").strip()
            maybe_end = str(raw.get("promoCode") or "").strip()
            if len(maybe_start) == 10 and len(maybe_end) == 10 and maybe_start.count("-") == 2 and maybe_end.count("-") == 2:
                raw["startDate"] = maybe_start
                raw["endDate"] = maybe_end
                raw["promoCode"] = None
        elif not raw.get("startDate") and start:
            raw["startDate"] = start
            raw["endDate"] = end
        return raw

    @model_validator(mode="after")
    def ensure_dates(self):
        if not (self.startDate or "").strip() or not (self.endDate or "").strip():
            raise ValueError("Укажите дату начала и дату окончания практики")
        self.startDate = self.startDate.strip()
        self.endDate = self.endDate.strip()
        return self


class ReferralCodeCreateIn(BaseModel):
    code: Annotated[str, StringConstraints(max_length=32)]


class ReferralCardBindIn(BaseModel):
    cardHolder: Annotated[str, StringConstraints(max_length=255)]
    bank: Annotated[str, StringConstraints(max_length=255)] | None = None


class AdminApplicationStatusIn(BaseModel):
    status: Annotated[str, StringConstraints(max_length=64)]


class AdminWithdrawalStatusIn(BaseModel):
    status: Annotated[str, StringConstraints(max_length=32)]
    adminNote: Annotated[str, StringConstraints(max_length=1000)] | None = None


class AdminUserUpdateIn(BaseModel):
    name: Name
    email: Email
    phone: Phone
    role: Annotated[str, StringConstraints(max_length=16)]
    referralCode: Annotated[str, StringConstraints(max_length=32)] | None = None


class AdminPromoCodeFreezeIn(BaseModel):
    frozen: bool
    note: Annotated[str, StringConstraints(max_length=1000)] | None = None
