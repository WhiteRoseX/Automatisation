#!/bin/zsh
cd "${0:A:h}" || exit 1
if [[ ! -x .venv/bin/python ]]; then
  echo "Installez l'environnement en suivant README.md."
  read -r "?Appuyez sur Entrée pour fermer."
  exit 1
fi
exec .venv/bin/python -m telepilot --live

