"""Qoida: rasmsiz e'lon yoki boshqa e'londan olingan rasm.

MVPda haqiqiy "stok rasm" tekshiruvi yo'q. Uning o'rniga: aynan shu rasm boshqa telefon
raqamli e'londa ham ishlatilgan bo'lsa (`reused_elsewhere`), ko'chirilgan rasm deb hisoblanadi.
"""

from __future__ import annotations

from elon.rules.base import Finding


def photos(*, has_photo: bool, reused_elsewhere: int = 0) -> Finding | None:
    if not has_photo:
        return Finding(code="no_photo", penalty=15, reason="E'londa rasm yo'q")
    if reused_elsewhere > 0:
        return Finding(
            code="photo_reused",
            penalty=30,
            reason="Shu rasm boshqa telefon raqamli e'londa ham ishlatilgan",
        )
    return None
