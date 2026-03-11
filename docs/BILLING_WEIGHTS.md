# Ponderation Chauffage / ECS

Ce document explique le choix par defaut de:

- `heating_weight = 0.65`
- `ecs_weight = 0.35`

dans `thermocalc.config.toml`.

## Conclusion pratique

Pour une chaudiere fioul Buderus residentielle autour de 2012, un reglage de depart `65 / 35` est plus defensable que `50 / 50` pour repartir une facture combustible totale entre:

- la part chauffage de chaque occupant
- la part ECS de chaque occupant

## Ce que signifie cette ponderation

Cette ponderation ne dit pas que 35% de l'energie utile devient toujours de l'ECS. Elle sert a convertir une facture combustible globale en deux composantes de repartition:

- une composante chauffage, repartie selon les parts de chauffe calculees par ThermoCalc
- une composante ECS, repartie selon les deltas ECS saisis

## Sources et base technique

### 1. Contexte Buderus

Buderus documente ses solutions comme des systemes complets associant chaudiere et production d'eau chaude sanitaire, ce qui confirme qu'une installation fioul residentielle de cette marque doit etre analysee comme un ensemble chauffage + ECS, pas comme un poste unique.

References de contexte produit:

- Buderus, gamme chaudiere residentielle Logano Plus KB / KB195i
- Buderus, gamme de ballons ECS Logalux

Pages consultees:

- https://www.buderus.com/gb/en/ocs/residential/logano-plus-kb195i-67389-p/
- https://www.buderus.com/gb/en/ocs/residential/logalux-lt-67817-p/

Note:

Ces pages ne donnent pas un ratio officiel de repartition de facture. Elles servent surtout a justifier le contexte systeme chaudiere + ballon ECS.

### 2. Base methodologique europeenne

La logique de separation chauffage / ECS est cohérente avec les methodes europeennes de calcul energetique des systemes, notamment la famille de normes EN 15316, qui traite separement:

- les besoins de chauffage des locaux
- les besoins d'eau chaude sanitaire
- les rendements systeme selon les usages

Reference utile:

- EN 15316, Energy performance of buildings - Method for calculation of system energy requirements and system efficiencies

### 3. Raison physique

Sur une chaudiere fioul non recente avec ballon ECS:

- le chauffage porte souvent la majeure partie de la consommation annuelle dans un logement classique
- l'ECS reste plus stable sur l'annee mais subit souvent des pertes de stockage et des cycles courts

En pratique, cela conduit souvent a des ordres de grandeur de type:

- `60 a 70%` chauffage
- `30 a 40%` ECS

## Pourquoi 65 / 35

Le choix `0.65 / 0.35` est un compromis pragmatique pour une installation residentielle fioul Buderus de cette periode:

- il evite le biais d'un `50 / 50` qui surestime souvent l'ECS
- il reste moins agressif qu'un `70 / 30` reserve plutot aux logements peu isoles ou aux hivers rigoureux
- il est compatible avec une chaudiere associee a un ballon ECS, cas frequent chez Buderus

## Quand ajuster

Utiliser plutot `0.70 / 0.30` si:

- maison peu isolee
- climat froid
- forte domination de la consommation de chauffage

Utiliser plutot `0.60 / 0.40` si:

- logement bien isole
- faible besoin de chauffage
- poids relatif de l'ECS plus eleve

## Limites

- ce n'est pas une valeur constructeur officielle Buderus de repartition de facture
- sans comptage separe chauffage / ECS, cela reste une estimation
- le meilleur reglage reste un calage sur l'historique reels du site

## Recommandation d'exploitation

Commencer avec `0.65 / 0.35`, puis verifier sur quelques factures et quelques mois de releves ECS si la repartition parait credible. Ajuster ensuite par pas de 5 points.