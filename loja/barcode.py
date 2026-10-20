"""Normalização e validação de códigos de barras (EAN-13, EAN-8, UPC-A) e códigos internos."""
import re

_CONTROL = re.compile(r"[\x00-\x1f\x7f\s]+")


def normalize(code):
    """Remove espaços/caracteres de controle (ex.: CR/LF/TAB enviados pelo leitor) e padroniza em maiúsculas."""
    if code is None:
        return ""
    return _CONTROL.sub("", str(code)).upper()


def check_digit_ok(code):
    """Valida o dígito verificador GS1 (EAN-8, UPC-A, EAN-13)."""
    if not code.isdigit() or len(code) < 2:
        return False
    digits = [int(c) for c in code]
    body, check = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def classify(code, force_internal=False):
    """Retorna (codigo_normalizado, tipo). Levanta ValueError se um código numérico de 8/12/13
    dígitos tiver dígito verificador inválido (a menos que seja marcado como código interno)."""
    code = normalize(code)
    if not code:
        return None, None
    if force_internal:
        return code, "INTERNO"
    if code.isdigit() and len(code) in (8, 12, 13):
        if not check_digit_ok(code):
            raise ValueError(
                f"O código {code} tem dígito verificador inválido para "
                f"{ {8: 'EAN-8', 12: 'UPC-A', 13: 'EAN-13'}[len(code)] }. "
                "Confira a digitação ou marque como código interno."
            )
        return code, {8: "EAN-8", 12: "UPC-A", 13: "EAN-13"}[len(code)]
    return code, "INTERNO"


def variants(code):
    """Formas equivalentes do mesmo código: UPC-A (12) lido como EAN-13 com zero à esquerda."""
    code = normalize(code)
    result = {code} if code else set()
    if code.isdigit():
        if len(code) == 12:
            result.add("0" + code)
        elif len(code) == 13 and code.startswith("0"):
            result.add(code[1:])
    return result
