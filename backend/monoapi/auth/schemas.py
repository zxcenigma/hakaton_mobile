from pydantic import ConfigDict, Field

from monoapi.helpers.pydantic import BaseModel

"""
Логика:
  - По дефолту User зашел в приложение и идет на signup, либо выбирает signin
  - Если signup - то ввод email и дальше опрос. -> Доступ
  - Если signin - то ввод email и код на email. -> Доступ
"""

# TODO: Email 2FA
class SignInSchema(BaseModel):
    username: str = Field(..., description="Username field")
    # code:  str      = Field(..., description="Code from Email Field", min_length=4, max_length=6)

    model_config = ConfigDict(strict=True,
                              json_schema_extra={
                                    "example": {
                                        "username": "username",                                        # "code": "email_code",
                                    },
                                }

                            )


class SignUpSchema(BaseModel):
    username: str = Field(..., description="Username Field", min_length=4, max_length=24)
    age: int = Field(..., description="Age Field")
    model_config = ConfigDict(strict=True,
                              json_schema_extra={
                                    "example": {
                                        "username": "username",
                                        "age": 11,
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
