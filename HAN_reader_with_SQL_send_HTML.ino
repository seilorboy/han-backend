#include <WiFiS3.h>

// ---- WiFi-tiedot ----
const char* ssid     = "MQTT_broker";
const char* password = "sahkolabra";

// ---- Palvelimen tiedot ----
const char* serverHost = "192.168.8.30"; //voidaan olla yhteydessä LAN ulkopuolelta
const int   serverPort = 5000; // Portti liikennöintiin
const char* serverPath = "/api/energy";

// ---- HAN UART ----
const uint32_t HAN_BAUD = 115200;
const size_t   LINE_BUF_SIZE = 256;

char lineBuffer[LINE_BUF_SIZE];
size_t linePos = 0;

int wifiStatus = WL_IDLE_STATUS;

void setup() {
  Serial.begin(115200);
  while (!Serial) {;}

  Serial.println("Aidon HAN + WiFi -> MySQL demo");

  // Käynnistetään HAN-serial
  Serial1.begin(HAN_BAUD);
  Serial.println("Serial1 (HAN) aloitettu, odotetaan dataa...");

  // Yhdistetaan WiFiin
  connectWiFi();
}

void loop() {
  // Jos WiFi tippuu, yritetään uudelleen
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi yhteys poikki, yritetaan uudelleen...");
    connectWiFi();
  }

  // Luetaan HAN-linja
  while (Serial1.available() > 0) {
    char c = (char)Serial1.read();

    if (linePos < LINE_BUF_SIZE - 1) {
      lineBuffer[linePos++] = c;
    }

    if (c == '\n') {
      lineBuffer[linePos] = '\0';
      processLine(lineBuffer);   // tämä voi lähettää tiedon eteenpäin
      linePos = 0;
    }
  }
}

void connectWiFi() {
  Serial.print("Yhdistetaan WiFiin: ");
  Serial.println(ssid);

  // Yritetään kunnes yhdistyy
  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("WiFi OK!");
  delay(2000);
  Serial.print("IP-osoite: ");
  Serial.println(WiFi.localIP());
}

// ---- HAN-rivin käsittely ----

void processLine(char* line) {
  Serial.print("Rivi: ");
  Serial.print(line);

  const char* patterns[] = {
    "1-0:1.8.0(",
    "1.8.0(",
    "1-1:1.8.0("
  };

  for (int i = 0; i < 3; i++) {
    char* p = strstr(line, patterns[i]);
    if (p != NULL) {
      p = strchr(p, '(');
      if (p != NULL) {
        p++;

        char valueStr[32];
        size_t vi = 0;
        while (*p != ')' && *p != '*' && *p != '\0' && vi < sizeof(valueStr) - 1) {
          valueStr[vi++] = *p++;
        }
        valueStr[vi] = '\0';

        double energy_kWh = atof(valueStr);

        Serial.print("-> Energia (kWh): ");
        Serial.println(energy_kWh, 3);

        // Lahetetaan palvelimelle
        sendEnergyToServer(energy_kWh);

      }
      return;
    }
  }
}

// ---- HTTP POST palvelimelle ----

void sendEnergyToServer(double energy_kWh) {
  WiFiClient client;

  Serial.print("Yhdistetaan palvelimeen ");
  Serial.print(serverHost);
  Serial.print(":");
  Serial.println(serverPort);

  if (!client.connect(serverHost, serverPort)) {
    Serial.println("Yhteys palvelimeen epaonnistui");
    return;
  }

  // Rakennetaan JSON
  String json = "{ \"energy_kwh\": ";
  json += String(energy_kWh, 3);
  json += " }";

  // HTTP POST -otsikot
  String request;
  request  = "POST ";
  request += serverPath;
  request += " HTTP/1.1\r\n";
  request += "Host: ";
  request += serverHost;
  request += "\r\n";
  request += "Content-Type: application/json\r\n";
  request += "Connection: close\r\n";
  request += "Content-Length: ";
  request += json.length();
  request += "\r\n\r\n";
  request += json;

  client.print(request);

  Serial.println("Lahetetty HTTP POST:");
  Serial.println(request);

  // Luetaan vastaus (debug)
  while (client.connected() || client.available()) {
    if (client.available()) {
      String line = client.readStringUntil('\n');
      Serial.println(line);
    }
  }

  client.stop();
  Serial.println("Yhteys suljettu");
}
