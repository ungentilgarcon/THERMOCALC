# Mode Test De Calculs

## Objectif

La page `/test-calculs` permet de verifier le comportement du moteur de repartition chauffage sur des cas controles.

La page `/test-consommation` reprend le meme principe mais ajoute une saisie ECS par occupant pour valider une synthese de consommation complete.

Elle sert a:

- rejouer des situations typiques sans attendre des mesures reelles
- comparer plusieurs hypotheses de surfaces ou consignes
- verifier qu'un changement de formule ne cree pas de regression evidente

## Ce que le mode test fait

- charge des scenarios predefinis
- permet d'editer chaque ligne de chauffe
- calcule instantanement un rapport complet chauffage
- affiche la repartition finale par occupant
- affiche le detail zone par zone
- peut aussi simuler des volumes ECS et leur allocation financiere par occupant
- peut aussi simuler une facture combustible totale, puis la combiner avec les parts chauffage et ECS

## Ce que le mode test ne fait pas

- n'ecrit pas dans `data/runtime_measurements.json`
- n'ecrit pas dans `data/admin_state.json`
- ne publie rien sur MQTT
- ne genere pas d'archive PDF

## Scenarios fournis

### Appartement equilibre

Cas nominal avec deux occupants et des besoins proches.

### Pointe sur salon

Cas ou une grande piece principale absorbe la majorite de la demande de chauffe.

### Abaissement nocturne

Cas avec retour de chauffe apres reduction nocturne, utile pour valider les deltas eleves et le duty cycle.

## Utilisation recommandee

1. Ouvrir `/test-calculs`.
2. Charger un scenario predefini ou choisir `Scenario manuel`.
3. Ajuster les lignes: occupant, zone, surface, consigne, temperature observee, vanne, `running_state`, duty cycle.
4. Executer le calcul.
5. Lire les parts finales et les scores detaillees.

Pour tester la consommation complete:

1. Ouvrir `/test-consommation`.
2. Charger un scenario de chauffe.
3. Saisir un volume ECS de test par occupant.
4. Saisir la facture combustible totale.
5. Executer le calcul et lire la synthese chauffage plus ECS.

Par defaut, ThermoCalc applique une ponderation `65/35` entre chauffage et ECS pour convertir la facture combustible totale en montant final par occupant. Cette ponderation est configurable dans `thermocalc.config.toml`.

Le pilotage chauffage `reel` ne passe pas par cette page de test. Pour configurer des profils rapides, des creneaux hebdomadaires, des overrides temporaires ou un mode vacances hors-gel par occupant, utiliser `/pilotage-chauffage`.

## Interprétation rapide

- une vanne plus ouverte augmente la demande
- un `running_state=heat` penalise plus fortement qu'un `idle`
- un duty cycle eleve confirme une chauffe recurrente recente
- une grande surface multiplie l'impact d'un meme delta

## Cas de validation utiles

- verifier qu'un occupant avec plus de surface ne gagne pas systematiquement sans delta
- verifier qu'un `idle` avec vanne faible reste secondaire
- verifier qu'une zone froide avec forte ouverture prend bien du poids
- verifier que la somme des parts finales atteint 100%