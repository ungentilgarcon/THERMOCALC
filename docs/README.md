# Documentation ThermoCalc

Cette documentation complete le README racine avec une vue exploitable par usage.

## Sommaire

- [API.md](API.md) : endpoints HTML, JSON, PDF et operations d'administration
- [ARCHITECTURE.md](ARCHITECTURE.md) : structure applicative et flux de donnees
- [BILLING_WEIGHTS.md](BILLING_WEIGHTS.md) : justification et sources de la ponderation chauffage / ECS
- [EXPLOITATION.md](EXPLOITATION.md) : installation, configuration, exploitation quotidienne
- [TEST_CALCULS.md](TEST_CALCULS.md) : mode de simulation et validation fonctionnelle

## Point d'entree rapide

- Interface utilisateur : `http://127.0.0.1:8000/`
- Documentation OpenAPI FastAPI : `http://127.0.0.1:8000/docs`
- Schema OpenAPI JSON : `http://127.0.0.1:8000/openapi.json`

## Perimetre

La documentation couvre:

- le suivi de chauffe TRV26
- le pilotage chauffage par occupant et par tete
- la repartition ECS
- l'administration Zigbee et archives
- le mode de test de calculs
- l'exploitation locale du service