from pydantic import EmailStr, ConfigDict, Field, SecretStr

from monoapi.helpers.pydantic import BaseModel

"""
Логика:
  - По дефолту User зашел в приложение и идет на signup, либо выбирает signin
  - Если signup - то ввод email и дальше опрос. -> Доступ
  - Если signin - то ввод email и код на email. -> Доступ
"""

# TODO: Email 2FA
class SignInSchema(BaseModel):
    email: EmailStr = Field(..., description="Email field")
    password: SecretStr = Field(min_length=8, max_length=64)
    # code:  str      = Field(..., description="Code from Email Field", min_length=4, max_length=6)

    model_config = ConfigDict(strict=True,
                              json_schema_extra={
                                    "example": {
                                        "email": "user@example.ru",
                                        "password": "password"
                                        # "code": "email_code",
                                    },
                                }

                            )


class SignUpSchema(BaseModel):
    email: EmailStr = Field(..., description="Email Field")
    username: str = Field(..., description="Username Field", min_length=4, max_length=24)
    password: SecretStr = Field(min_length=8, max_length=64)

    model_config = ConfigDict(strict=True,
                              json_schema_extra={
                                    "example": {
                                        "email": "user@example.ru",
                                        "username": "username",
                                        "password": "password"
                                    },
                                }
                            )
    

class ResponseSignUp(BaseModel):
    status: str = Field(default="Success")
    detail: str = Field(default="Вы успешно зарегистрировались")


class VerifiedCodeFromEmail(): ...


class TokenInfoSchema(BaseModel):
    access_token: str
    token_type: str = "Bearer"
