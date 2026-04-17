# Elite Dangerous - Plug

Logiciel local en français, pensé comme un "Inara en logiciel", mais orienté commerce, fraîcheur maximale et simplicité d'utilisation.

## Sources utilisées

- Journaux locaux du jeu
- `Market.json`, `Status.json`, `Cargo.json`
- API Ardent
- API Spansh
- API EDSM
- Flux EDDN en temps réel

## Objectif produit

- importer automatiquement la situation du commandant
- synchroniser les données de commerce de la zone utile
- recalculer rapidement les meilleures routes
- rendre visible la fraîcheur réelle des données
- rester simple à utiliser pour un joueur qui veut surtout trader

## Lancement rapide en développement

1. Double-cliquer sur `lancer_elite_plug.cmd`
2. Une fenêtre native Windows s'ouvre automatiquement
3. Importer les journaux
4. Scanner la région via Ardent
5. Démarrer EDDN pour garder les prix très frais

## Construction du .exe

1. Double-cliquer sur `build_exe.cmd`
2. Attendre la fin de la compilation PyInstaller
3. Lancer `dist\Elite Dangerous - Plug\Elite Dangerous - Plug.exe`

## Remarque importante

Le "temps réel partout dans la galaxie" dépend des contributions disponibles. Le logiciel empile donc plusieurs couches :

- source locale exacte depuis le jeu
- synchro régionale rapide via API
- revalidation ciblée du marché courant
- flux live EDDN

## Suite logique

- bibliothèque FR de noms du jeu enrichie automatiquement
- plus d'écrans type Inara : station, marché, services, historique
- enrichissement des modules et composants avec libellés français
