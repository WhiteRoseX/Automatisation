"""macOS Keychain access through Security.framework, without shell arguments."""

import ctypes as c
import sys

from .core.models import DomainError


class Keychain:
    SERVICE = b"app.telepilot.desktop"

    def __init__(self):
        self.lib = None
        if sys.platform == "darwin":
            self.lib = c.CDLL("/System/Library/Frameworks/Security.framework/Security")
            self.cf = c.CDLL(
                "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
            )
            self.lib.SecKeychainFindGenericPassword.argtypes = [
                c.c_void_p,
                c.c_uint32,
                c.c_char_p,
                c.c_uint32,
                c.c_char_p,
                c.POINTER(c.c_uint32),
                c.POINTER(c.c_void_p),
                c.POINTER(c.c_void_p),
            ]
            self.lib.SecKeychainAddGenericPassword.argtypes = [
                c.c_void_p,
                c.c_uint32,
                c.c_char_p,
                c.c_uint32,
                c.c_char_p,
                c.c_uint32,
                c.c_char_p,
                c.c_void_p,
            ]
            self.lib.SecKeychainItemModifyAttributesAndData.argtypes = [
                c.c_void_p,
                c.c_void_p,
                c.c_uint32,
                c.c_char_p,
            ]
            self.lib.SecKeychainItemFreeContent.argtypes = [c.c_void_p, c.c_void_p]
            self.cf.CFRelease.argtypes = [c.c_void_p]

    def get(self, account):
        if not self.lib:
            return None
        account = account.encode()
        length, data = c.c_uint32(), c.c_void_p()
        status = self.lib.SecKeychainFindGenericPassword(
            None,
            len(self.SERVICE),
            self.SERVICE,
            len(account),
            account,
            c.byref(length),
            c.byref(data),
            None,
        )
        if status == -25300:
            return None
        if status:
            raise DomainError(
                "Le trousseau macOS n'est pas accessible. Saisissez à nouveau votre API hash."
            )
        try:
            return c.string_at(data, length.value).decode()
        finally:
            self.lib.SecKeychainItemFreeContent(None, data)

    def set(self, account, secret):
        if not self.lib:
            raise DomainError(
                "Le trousseau est disponible uniquement sur macOS. Le secret peut être utilisé sans être enregistré."
            )
        account, secret = account.encode(), secret.encode()
        item = c.c_void_p()
        status = self.lib.SecKeychainFindGenericPassword(
            None,
            len(self.SERVICE),
            self.SERVICE,
            len(account),
            account,
            None,
            None,
            c.byref(item),
        )
        if status == -25300:
            status = self.lib.SecKeychainAddGenericPassword(
                None,
                len(self.SERVICE),
                self.SERVICE,
                len(account),
                account,
                len(secret),
                secret,
                None,
            )
        elif status == 0:
            try:
                status = self.lib.SecKeychainItemModifyAttributesAndData(
                    item, None, len(secret), secret
                )
            finally:
                self.cf.CFRelease(item)
        if status:
            raise DomainError(
                "L'enregistrement dans le trousseau macOS a échoué. Aucun secret n'a été enregistré dans la base."
            )
