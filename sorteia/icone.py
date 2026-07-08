"""Gera os ícones PNG do SorteIA em Python puro (sem Pillow).

Desenha um trevo branco sobre um quadrado arredondado com degradê verde,
com antialiasing simples, e codifica o PNG na mão (zlib + struct).
"""

from __future__ import annotations

import math
import struct
import zlib

_cache: dict[int, bytes] = {}

_VERDE_TOPO = (46, 222, 131)
_VERDE_BASE = (13, 122, 66)
_BRANCO = (255, 255, 255)


def _png_rgba(tamanho: int, linhas: list[bytearray]) -> bytes:
    def bloco(tipo: bytes, dados: bytes) -> bytes:
        return (struct.pack(">I", len(dados)) + tipo + dados
                + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", tamanho, tamanho, 8, 6, 0, 0, 0)
    bruto = b"".join(b"\x00" + bytes(linha) for linha in linhas)
    return (b"\x89PNG\r\n\x1a\n"
            + bloco(b"IHDR", ihdr)
            + bloco(b"IDAT", zlib.compress(bruto, 9))
            + bloco(b"IEND", b""))


def _suave(borda: float, distancia: float) -> float:
    """Cobertura antialiasada: 1 dentro, 0 fora, rampa de ~1.5px na borda."""
    return max(0.0, min(1.0, (borda - distancia) / 1.5))


def gerar(tamanho: int) -> bytes:
    if tamanho in _cache:
        return _cache[tamanho]

    n = tamanho
    metade = n / 2.0
    raio_canto = n * 0.23
    interno = metade - raio_canto

    # trevo: 4 folhas circulares + caule
    cx, cy = metade, n * 0.46
    desloc = n * 0.115
    raio_folha = n * 0.145
    folhas = [(cx + sx * desloc, cy + sy * desloc)
              for sx in (-1, 1) for sy in (-1, 1)]
    caule_larg = n * 0.030
    caule_fim = cy + n * 0.30

    linhas: list[bytearray] = []
    for y in range(n):
        linha = bytearray()
        for x in range(n):
            px, py = x + 0.5, y + 0.5

            # máscara do quadrado arredondado
            dx = max(abs(px - metade) - interno, 0.0)
            dy = max(abs(py - metade) - interno, 0.0)
            alfa = _suave(raio_canto, math.hypot(dx, dy))
            if alfa <= 0.0:
                linha += b"\x00\x00\x00\x00"
                continue

            # fundo em degradê vertical
            t = py / n
            cor = [round(a + (b - a) * t) for a, b in zip(_VERDE_TOPO, _VERDE_BASE)]

            # cobertura do trevo (folhas + caule)
            cobertura = 0.0
            for fx, fy in folhas:
                cobertura = max(cobertura,
                                _suave(raio_folha, math.hypot(px - fx, py - fy)))
            if cy <= py <= caule_fim:
                cobertura = max(cobertura, _suave(caule_larg, abs(px - cx)))
            if cobertura > 0.0:
                cor = [round(c + (b - c) * cobertura)
                       for c, b in zip(cor, _BRANCO)]

            linha += bytes(cor) + bytes([round(255 * alfa)])
        linhas.append(linha)

    _cache[tamanho] = _png_rgba(n, linhas)
    return _cache[tamanho]
