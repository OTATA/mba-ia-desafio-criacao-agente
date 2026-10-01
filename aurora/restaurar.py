"""Restaura reservas e visitantes para o estado de dados/*.json (sessões são mantidas)."""
from . import db

if __name__ == "__main__":
    db.restaurar()
    print("Dados restaurados.")
