ESPERA_EN_PARADA_S = 25

RUTAS = [
    {
        "nombre": "R1 Centro - Poblado",
        "color": "#d62828",
        "velocidad_kmh": 22,
        "buses": 2,
        "circular": False,
        "paradas": [
            ("Parque Berrío",      6.2502, -75.5682),
            ("San Antonio",        6.2472, -75.5697),
            ("Alpujarra",          6.2449, -75.5735),
            ("Exposiciones",       6.2383, -75.5732),
            ("Industriales",       6.2300, -75.5756),
            ("Estación Poblado",   6.2126, -75.5779),
            ("Parque del Poblado", 6.2104, -75.5707),
        ],
        "coordenadas": [
            (6.2502, -75.5682), (6.2472, -75.5697), (6.2449, -75.5735),
            (6.2383, -75.5732), (6.2300, -75.5756), (6.2126, -75.5779),
            (6.2104, -75.5707),
        ],
    },
    {
        "nombre": "R2 Centro - San Javier",
        "color": "#1d4ed8",
        "velocidad_kmh": 20,
        "buses": 2,
        "circular": False,
        "paradas": [
            ("San Antonio",  6.2472, -75.5697),
            ("Cisneros",     6.2491, -75.5749),
            ("Suramericana", 6.2530, -75.5829),
            ("Estadio",      6.2533, -75.5883),
            ("Floresta",     6.2587, -75.5977),
            ("San Javier",   6.2567, -75.6134),
        ],
        "coordenadas": [
            (6.2472, -75.5697), (6.2491, -75.5749), (6.2530, -75.5829),
            (6.2533, -75.5883), (6.2587, -75.5977), (6.2567, -75.6134),
        ],
    },
    {
        "nombre": "R3 Circular Norte",
        "color": "#15803d",
        "velocidad_kmh": 24,
        "buses": 2,
        "circular": True,
        "paradas": [
            ("Parque Berrío",            6.2502, -75.5682),
            ("Prado",                    6.2570, -75.5661),
            ("Hospital",                 6.2639, -75.5633),
            ("Universidad de Antioquia", 6.264789, -75.569457),
            ("Terminal del Norte",       6.2779, -75.5694),
            ("Universidad Nacional",     6.2617, -75.5773),
        ],
        "coordenadas": [
            (6.2502, -75.5682), (6.2570, -75.5661), (6.2639, -75.5633),
            (6.264789, -75.569457), (6.265128, -75.571600), (6.2779, -75.5694), (6.2617, -75.5773),
            (6.2502, -75.5682),
        ],
    },
]