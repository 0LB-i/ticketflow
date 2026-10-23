"""Os testes rodam no fuso de São Paulo, qualquer que seja o da máquina (core/timezone.py).

Fica aqui, e não no conftest, porque este arquivo é importado antes de qualquer `chamados`.
"""

import os

os.environ["TZ"] = "America/Sao_Paulo"
