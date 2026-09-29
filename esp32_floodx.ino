/*
 * FloodX 2.0 - ESP32 street node: sensors + local flood actuators
 * ===============================================================
 * One street unit: 1 flow sensor, 1 water-level sensor, 1 rain sensor,
 * 3 status LEDs, 1 buzzer and 2x two-channel relay modules (4 outputs).
 *
 * The node runs the whole flood logic LOCALLY (pump / lamp / barrier /
 * siren work with no server and no WiFi) and POSTs one JSON reading per
 * cycle to the FloodX API:
 *
 *   POST http://192.168.1.100:8000/ingest     (HTTPS_USE = 0, your PC)
 *   POST https://floodx.onrender.com/ingest   (HTTPS_USE = 1, cloud)
 *
 *   {"timestamp":"2026-09-25 14:32:05","zone":"Zone_3",
 *    "rainfall_intensity_mm_hr":74.0,"water_level_cm":38.2,
 *    "flow_rate_lps":126.0,"drain_capacity_lps":150.0,
 *    "blockage_pct":38.0,"drain_saturation_pct":84,"flood_next_30min":1,
 *    "rain_detected":1,"pump_on":1,"alarm_level":3}
 *
 * Wiring
 * ------
 *   YF-S201 flow sensor OUT   -> GPIO 13   (5 V out: divider to 3.3 V)
 *   HC-SR04 water level TRIG  -> GPIO 26
 *   HC-SR04 water level ECHO  -> GPIO 27   (3.3 V module preferred)
 *   Rain sensor OUT / AO       -> GPIO 34   (input only, ADC1_CH6,
 *                                add a 10 k pull-up if it is digital only)
 *   Green / yellow / red LED   -> GPIO 18 / 19 / 21  (220-330 R to GND)
 *   Buzzer module IN           -> GPIO 23
 *   Relay module A ch1 / ch2   -> GPIO 22 / 25   (drain pump, flood lamp)
 *   Relay module B ch1 / ch2   -> GPIO 16 / 17   (barrier, siren amplifier)
 *
 * Local behaviour (no server needed)
 *   green  LED : normal
 *   yellow LED : rising water / moderate rain
 *   red    LED : flood risk - pump runs, warning lamp on, siren + buzzer,
 *               barrier closes on the top alert level
 *   pump relay: ON above PUMP_ON_CM, OFF below PUMP_OFF_CM, dry-run and
 *               max-run protected (relay drops out on a fault)
 *
 * After uploading, open the dashboard at http://<pc-ip>:8000/v2
 * it screens on one reading at boot and then follows YOUR sensor live.
 */
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <time.h>

// ── Wi-Fi ────────────────────────────────────────────────────────
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";

// ── Server ───────────────────────────────────────────────────────
// HTTPS_USE = 1 -> https://SERVER_HOST/SERVER_PATH          (cloud)
// HTTPS_USE = 0 -> http://SERVER_HOST:SERVER_PORT/SERVER_PATH  (LAN)
#define HTTPS_USE 0
const char* SERVER_HOST = "192.168.1.100";   // no scheme, no trailing slash
const char* SERVER_PATH = "/ingest";
const int   SERVER_PORT = 8000;

// ── Sensor wiring ────────────────────────────────────────────────
const int PIN_FLOW      = 13;   // YF-S201 pulse out
const int PIN_ULTR_TRIG = 26;   // HC-SR04 trigger
const int PIN_ULTR_ECHO = 27;   // HC-SR04 echo
const int PIN_RAIN      = 34;   // rain sensor OUT / AO (input only)

// ── Actuator wiring ──────────────────────────────────────────────
const int PIN_LED_GREEN  = 18;
const int PIN_LED_YELLOW = 19;
const int PIN_LED_RED    = 21;
const int PIN_BUZZER     = 23;
const int PIN_RELAY_A1   = 22;   // module A ch1 -> drain pump
const int PIN_RELAY_A2   = 25;   // module A ch2 -> flood warning lamp
const int PIN_RELAY_B1   = 16;   // module B ch1 -> barrier / gate
const int PIN_RELAY_B2   = 17;   // module B ch2 -> siren amplifier

// ── Output polarity (flip for active-HIGH boards) ────────────────
#define RELAY_ACTIVE_LOW  1   // most 2-channel relay modules pull low to fire
#define BUZZER_ACTIVE_HIGH 1   // most buzzer modules drive high to sound

// ── Rain sensor calibration ──────────────────────────────────────
#define RAIN_ANALOG           1      // 1 = analog AO, 0 = digital switch
#define RAIN_ACTIVE_LOW       1      // digital mode: LOW while it is raining
const int   RAIN_ADC_DRY      = 2200; // ADC count when bone dry
const int   RAIN_ADC_WET      = 900;  // ADC count when soaked
const float RAIN_MM_HR_MAX    = 90.0f;// intensity reported at RAIN_ADC_WET
const float RAIN_MM_HR_NOMINAL = 25.0f;// digital modules: fixed fallback rate
const float RAIN_WARN_MM_HR   = 5.0f; // yellow above this
const float RAIN_ALERT_MM_HR  = 25.0f;// red above this

// ── Street identity + thresholds ─────────────────────────────────
const char*  ZONE         = "Zone_3";    // Zone_1..Zone_8
const float  DRAIN_CAP    = 150.0f;      // L/s drain capacity for this street
const float  BLOCKAGE_PCT = 38.0f;       // current drain blockage (%)
const float  DEPTH_WARN_CM = 20.0f;      // yellow LED
const float  DEPTH_ALERT_CM = 30.0f;     // red LED
const float  DEPTH_CRIT_CM  = 40.0f;     // barrier + siren
const float  SAT_WARN_PCT   = 75.0f;
const float  SAT_ALERT_PCT  = 90.0f;

// ── Pump control ─────────────────────────────────────────────────
const float PUMP_ON_CM        = 15.0f;   // start pump (hysteresis top)
const float PUMP_OFF_CM       = 8.0f;    // stop pump  (hysteresis bottom)
const float PUMP_DRY_FLOW_LPS = 0.30f;   // below this the pump is not moving water
const unsigned long PUMP_MAX_RUN_MS     = 15UL * 60UL * 1000UL;   // 15 min max run
const unsigned long PUMP_FAULT_CLEAR_MS = 5UL * 60UL * 1000UL;    // retry after 5 min
const unsigned long BARRIER_MIN_HOLD_MS = 5UL * 60UL * 1000UL;   // no flapping

// ── Timing ───────────────────────────────────────────────────────
const unsigned long TICK_MS       = 100;   // sensor + logic tick
const unsigned long FLOW_WIN_MS   = 1000;  // flow measurement window
const unsigned long SEND_EVERY_MS = 5000;  // one POST every 5 s
const unsigned long BEEP_TICK_MS  = 200;   // buzzer pattern tick
const unsigned long SELF_TEST_MS  = 300;   // boot self-test dwell per output
#define SELF_TEST_ON_BOOT 1
const long GMT_OFFSET_SEC = 19800;        // IST = UTC + 5h30m
const int  DST_OFFSET_SEC = 0;            // India has no DST

// ── Flow calibration + state ─────────────────────────────────────
volatile unsigned long flowPulses = 0;
const float PULSES_PER_LITRE = 450.0f;    // YF-S201 nominal

float   flowLps      = 0.0f;
float   depthCm      = -1.0f;             // -1 = no valid echo yet
float   rainMmHr     = 0.0f;
bool    rainDetected = false;
bool    sensorFault  = false;             // level sensor not answering
int     alarmLevel   = 0;                 // 0 none, 1 warn, 2 alert, 3 flood
bool    pumpOn       = false;
bool    pumpFault    = false;
bool    barrierShut  = false;
unsigned long pumpStartedAt   = 0;
unsigned long barrierShutAt   = 0;
unsigned long flowWinAt       = 0;
unsigned long tickAt          = 0;
unsigned long sendAt          = 0;
unsigned long beepTickAt      = 0;
unsigned long lastWarnChirpAt = 0;
unsigned long levelFaultAt    = 0;
unsigned long lastPrintAt     = 0;
int      beepWindow   = 0;
int      beepPhase    = 0;
bool     prevRain     = false;

WiFiClientSecure secureClient;
WiFiClient       plainClient;

void IRAM_ATTR onFlow(){ flowPulses++; }

// ── Output helpers ───────────────────────────────────────────────
void setRelay(int pin, bool on){
#if RELAY_ACTIVE_LOW
  digitalWrite(pin, on ? LOW : HIGH);
#else
  digitalWrite(pin, on ? HIGH : LOW);
#endif
}

void setBuzzer(bool on){
#if BUZZER_ACTIVE_HIGH
  digitalWrite(PIN_BUZZER, on ? HIGH : LOW);
#else
  digitalWrite(PIN_BUZZER, on ? LOW : HIGH);
#endif
}

void setLeds(int level, unsigned long now){
  bool green  = (level == 0);
  bool yellow = (level == 1);
  bool red    = (level >= 2);
  if (level >= 3) red = (((now / 250UL) % 2UL) == 0UL);   // strobe on flood
  digitalWrite(PIN_LED_GREEN,  green  ? HIGH : LOW);
  digitalWrite(PIN_LED_YELLOW, yellow ? HIGH : LOW);
  digitalWrite(PIN_LED_RED,    red    ? HIGH : LOW);
}

void allOutputsOff(){
  setRelay(PIN_RELAY_A1, false); setRelay(PIN_RELAY_A2, false);
  setRelay(PIN_RELAY_B1, false); setRelay(PIN_RELAY_B2, false);
  setBuzzer(false);
  digitalWrite(PIN_LED_GREEN, LOW);
  digitalWrite(PIN_LED_YELLOW, LOW);
  digitalWrite(PIN_LED_RED, LOW);
}

void selfTest(){
#if SELF_TEST_ON_BOOT
  const int pins[] = { PIN_LED_GREEN, PIN_LED_YELLOW, PIN_LED_RED, PIN_BUZZER,
                       PIN_RELAY_A1, PIN_RELAY_A2, PIN_RELAY_B1, PIN_RELAY_B2 };
  for (int i = 0; i < 8; i++){
    Serial.printf("self-test GPIO %d\n", pins[i]);
    digitalWrite(pins[i], HIGH);
    setRelay(PIN_RELAY_A1, i == 4);
    setRelay(PIN_RELAY_A2, i == 5);
    setRelay(PIN_RELAY_B1, i == 6);
    setRelay(PIN_RELAY_B2, i == 7);
    setBuzzer(i == 3);
    delay(SELF_TEST_MS);
    digitalWrite(pins[i], LOW);
    setRelay(PIN_RELAY_A1, false); setRelay(PIN_RELAY_A2, false);
    setRelay(PIN_RELAY_B1, false); setRelay(PIN_RELAY_B2, false);
    setBuzzer(false);
    delay(60);
  }
  allOutputsOff();
  Serial.println("self-test done");
#endif
}

// ── Sensors ──────────────────────────────────────────────────────
float readDepthCm(){
  float s[5];
  for (int i = 0; i < 5; i++){
    digitalWrite(PIN_ULTR_TRIG, LOW);   delayMicroseconds(2);
    digitalWrite(PIN_ULTR_TRIG, HIGH);  delayMicroseconds(10);
    digitalWrite(PIN_ULTR_TRIG, LOW);
    long us = pulseIn(PIN_ULTR_ECHO, HIGH, 20000);
    s[i] = (us == 0) ? -1.0f : (us * 0.0343f) / 2.0f;   // cm
    delay(5);
  }
  for (int i = 1; i < 5; i++){          // median of 5 kills HC-SR04 spikes
    for (int j = i; j > 0 && s[j] < s[j - 1]; j--){
      float t = s[j]; s[j] = s[j - 1]; s[j - 1] = t;
    }
  }
  if (s[2] < 0) return -1.0f;            // out of range / no echo
  return constrain(s[2], 0.0f, 500.0f);
}

float readRainMmHr(){
#if RAIN_ANALOG
  int raw = analogRead(PIN_RAIN);
  if (raw >= RAIN_ADC_DRY) return 0.0f;
  if (raw <= RAIN_ADC_WET) return RAIN_MM_HR_MAX;
  return RAIN_MM_HR_MAX * (float)(RAIN_ADC_DRY - raw) /
                          (float)(RAIN_ADC_DRY - RAIN_ADC_WET);
#else
  bool wet = digitalRead(PIN_RAIN);
#if RAIN_ACTIVE_LOW
  wet = !wet;
#endif
  return wet ? RAIN_MM_HR_NOMINAL : 0.0f;
#endif
}

int classify(float depth, float sat){
  if (sensorFault) return 3;
  if (depth >= DEPTH_CRIT_CM || (depth >= DEPTH_ALERT_CM && sat >= SAT_ALERT_PCT)) return 3;
  if (depth >= DEPTH_ALERT_CM || sat >= SAT_ALERT_PCT || rainMmHr >= RAIN_ALERT_MM_HR) return 2;
  if (depth >= DEPTH_WARN_CM || sat >= SAT_WARN_PCT || rainMmHr >= RAIN_WARN_MM_HR) return 1;
  return 0;
}

// ── Local actuation ──────────────────────────────────────────────
void updateFlow(unsigned long now){
  if (now - flowWinAt < FLOW_WIN_MS) return;
  float instant = flowPulses / PULSES_PER_LITRE;   // window = 1 s => L/s
  flowPulses = 0;
  flowWinAt  = now;
  flowLps = flowLps * 0.4f + instant * 0.6f;         // light smoothing
  if (flowLps < 0.01f) flowLps = 0.0f;
}

void updateActuators(unsigned long now){
  float effDepth = sensorFault ? PUMP_ON_CM : depthCm;   // fail-safe: pump on

  // pump: hysteresis, dry-run guard, max-run guard
  if (!pumpOn && effDepth >= PUMP_ON_CM && !pumpFault){
    pumpOn = true;
    pumpStartedAt = now;
    Serial.println("[pump] ON");
  } else if (pumpOn && (effDepth <= PUMP_OFF_CM ||
                        (now - pumpStartedAt) >= PUMP_MAX_RUN_MS)){
    pumpOn = false;
    Serial.println("[pump] OFF");
  }
  if (pumpOn && flowLps < PUMP_DRY_FLOW_LPS){
    if (now - pumpStartedAt > 10000UL){                  // 10 s with no flow
      pumpOn = false;
      pumpFault = true;
      Serial.println("[pump] FAULT (no flow) - relay dropped out");
    }
  } else if (!pumpOn && flowLps > PUMP_DRY_FLOW_LPS &&
             now - pumpStartedAt > PUMP_FAULT_CLEAR_MS){
    pumpFault = false;                                   // water moving again
  }
  setRelay(PIN_RELAY_A1, pumpOn);

  setRelay(PIN_RELAY_A2, alarmLevel >= 2);               // flood warning lamp

  // barrier: shut on flood, re-open only after the min hold time
  if (!barrierShut && alarmLevel >= 3){
    barrierShut = true;
    barrierShutAt = now;
    Serial.println("[barrier] CLOSED");
  } else if (barrierShut && (now - barrierShutAt) > BARRIER_MIN_HOLD_MS &&
             effDepth <= DEPTH_WARN_CM){
    barrierShut = false;
    Serial.println("[barrier] OPEN");
  }
  setRelay(PIN_RELAY_B1, barrierShut);
}

void updateBuzzer(unsigned long now){
  if (rainDetected && !prevRain) beepWindow = 6;          // rain-started chirp
  if (now - beepTickAt < BEEP_TICK_MS) return;
  beepTickAt = now;
  if (beepWindow > 0) beepWindow--;

  bool on = false;
  if      (beepWindow > 0)      on = (beepPhase < 2);    // chirp: 2 on, 3 off
  else if (alarmLevel == 2)     on = (beepPhase < 2);    // alert: 2 on, 3 off
  else if (alarmLevel >= 3)     on = (beepPhase < 3);    // flood: 3 on, 2 off
  else if (alarmLevel == 1 && beepPhase == 0 &&
           now - lastWarnChirpAt > 20000UL){
    on = true;
    lastWarnChirpAt = now;
  }
  beepPhase = (beepPhase + 1) % 5;
  setBuzzer(on);
  setRelay(PIN_RELAY_B2, on);                            // siren amp follows
}

// ── Networking ───────────────────────────────────────────────────
void connectWifi(){
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.println("WiFi down, reconnecting...");
  WiFi.reconnect();
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000UL){
    delay(250);
    Serial.print('.');
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED){
    Serial.println("IP: " + WiFi.localIP().toString());
    configTime(GMT_OFFSET_SEC, DST_OFFSET_SEC, "pool.ntp.org", "time.nist.gov");
  }
}

char* buildTimestamp(char* buf, size_t n){
  struct tm t;
  if (!getLocalTime(&t) || t.tm_year + 1900 < 2020){
    snprintf(buf, n, "1970-01-01 00:00:00");
    return buf;
  }
  snprintf(buf, n, "%04d-%02d-%02d %02d:%02d:%02d",
           t.tm_year + 1900, t.tm_mon + 1, t.tm_mday,
           t.tm_hour, t.tm_min, t.tm_sec);
  return buf;
}

int upload(const char* body){
  HTTPClient http;
  String url = HTTPS_USE ? (String("https://") + SERVER_HOST + SERVER_PATH)
                         : (String("http://") + SERVER_HOST + ":" +
                            SERVER_PORT + SERVER_PATH);
  if (HTTPS_USE){
    secureClient.setTimeout(8000);
    if (!http.begin(secureClient, url)) return -999;
  } else {
    plainClient.setTimeout(8000);
    if (!http.begin(plainClient, url)) return -999;
  }
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(body);
  if (code > 0) Serial.printf("POST %s -> %d  %s\n", url.c_str(), code,
                              http.getString().c_str());
  else          Serial.printf("POST %s failed -> %d\n", url.c_str(), code);
  http.end();
  return code;
}

void sendReading(unsigned long now){
  if (now - sendAt < SEND_EVERY_MS) return;
  sendAt = now;
  if (WiFi.status() != WL_CONNECTED) return;             // retry next cycle

  char ts[20];
  buildTimestamp(ts, sizeof(ts));

  int   sat   = constrain((int)(flowLps / DRAIN_CAP * 100.0f), 0, 125);
  int   flood = (alarmLevel >= 3) ? 1 : 0;

  char body[512];
  snprintf(body, sizeof(body),
           "{\"timestamp\":\"%s\",\"zone\":\"%s\","
           "\"rainfall_intensity_mm_hr\":%.1f,\"water_level_cm\":%.1f,"
           "\"flow_rate_lps\":%.2f,\"drain_capacity_lps\":%.1f,"
           "\"blockage_pct\":%.1f,\"drain_saturation_pct\":%d,"
           "\"flood_next_30min\":%d,"
           "\"rain_detected\":%d,\"pump_on\":%d,\"alarm_level\":%d}",
           ts, ZONE, rainMmHr, depthCm < 0 ? 0.0f : depthCm, flowLps,
           DRAIN_CAP, BLOCKAGE_PCT, sat, flood,
           rainDetected ? 1 : 0, pumpOn ? 1 : 0, alarmLevel);

  const unsigned long t0 = millis();
  int tries = 0, code = -1;
  do {
    tries++;
    code = upload(body);
    if (code == 200 || code == 201) break;
    delay(2000);                       // wait before retry (server cold start)
  } while (tries < 3 && millis() - t0 < 20000);
}

// ── Arduino entry points ─────────────────────────────────────────
void setup(){
  Serial.begin(115200);
  pinMode(PIN_FLOW, INPUT);
  attachInterrupt(digitalPinToInterrupt(PIN_FLOW), onFlow, FALLING);
  pinMode(PIN_ULTR_TRIG, OUTPUT);
  pinMode(PIN_ULTR_ECHO, INPUT);
  pinMode(PIN_RAIN, INPUT);

  const int out[] = { PIN_LED_GREEN, PIN_LED_YELLOW, PIN_LED_RED, PIN_BUZZER,
                      PIN_RELAY_A1, PIN_RELAY_A2, PIN_RELAY_B1, PIN_RELAY_B2 };
  for (int i = 0; i < 8; i++) pinMode(out[i], OUTPUT);
  allOutputsOff();                     // relays idle before WiFi comes up

  Serial.println("\nFloodX street node booting");
  selfTest();

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED){ delay(500); Serial.print('.'); }
  Serial.println("\nIP: " + WiFi.localIP().toString());

  configTime(GMT_OFFSET_SEC, DST_OFFSET_SEC, "pool.ntp.org", "time.nist.gov");
  secureClient.setInsecure();          // skip TLS certificate verification

  tickAt = flowWinAt = sendAt = millis();
}

void loop(){
  const unsigned long now = millis();
  if (now - tickAt < TICK_MS) return;
  tickAt = now;

  updateFlow(now);

  float sample = readDepthCm();
  if (sample < 0){
    if (levelFaultAt == 0) levelFaultAt = now;
    else if (now - levelFaultAt > 15000UL) sensorFault = true;   // 15 s dead
  } else {
    levelFaultAt = 0;
    sensorFault  = false;
    depthCm = (depthCm < 0) ? sample : depthCm * 0.6f + sample * 0.4f;
  }

  rainMmHr     = readRainMmHr();
  rainDetected = rainMmHr > 1.0f;

  int sat = constrain((int)(flowLps / DRAIN_CAP * 100.0f), 0, 125);
  alarmLevel = classify(depthCm < 0 ? PUMP_ON_CM : depthCm, sat);

  updateActuators(now);
  setLeds(alarmLevel, now);
  updateBuzzer(now);
  prevRain = rainDetected;

  if (now - lastPrintAt >= 2000UL){
    lastPrintAt = now;
    Serial.printf("lvl=%d depth=%.1fcm flow=%.2fL/s rain=%.1fmm/h sat=%d%% "
                  "pump=%d barrier=%d rain=%d%s\n",
                  alarmLevel, depthCm < 0 ? 0.0f : depthCm, flowLps, rainMmHr,
                  sat, pumpOn, barrierShut, rainDetected,
                  sensorFault ? " SENSOR_FAULT" : "");
  }

  sendReading(now);
  connectWifi();
}
