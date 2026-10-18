/*
  Controlador de telescopio Dobsoniano  (2 eixos: AZimute e ALTitude)
  --------------------------------------------------------------------
  Placa    : Arduino Duemilanove (ATmega328P, logica 5V)
  Drivers  : 2x DRV8825 (um por eixo)
  Motores  : 2x NEMA 17
  Radio    : HC-06 (Bluetooth) ligado por SoftwareSerial a 9600 bps
  Canais   : aceita comandos pelo HC-06 E pelo cabo USB (9600 bps); responde
             pelo canal de onde veio cada comando
  Lib      : AccelStepper  (instale pelo Gerenciador de Bibliotecas da IDE)

  FILOSOFIA: o PC e o cerebro. Ele calcula coordenadas e manda comandos
  de texto. Este firmware so EXECUTA movimentos, sempre em PASSOS.
  Quem converte angulo->passos (usando reducao e microstep) e o PC.

  Protocolo (linhas terminadas por '\n' ou '\r'):
    PING                 -> responde "PONG"
    POS?                 -> responde "POS AZ=<n> ALT=<n>"
    MOVE AZ <delta>      -> move o azimute <delta> passos (relativo, com rampa)
    MOVE ALT <delta>     -> idem para a altitude
    GOTO AZ <pos>        -> vai para a posicao absoluta <pos> passos (com rampa)
    GOTO ALT <pos>
    JOG AZ <dir>         -> movimento continuo ate STOP: dir = 1, -1 ou 0
    JOG ALT <dir>
    RATE AZ <sps>        -> velocidade constante <sps> passos/s (com sinal,
    RATE ALT <sps>          aceita fracao). Usado no RASTREAMENTO: o PC
                            recalcula e reenvia a cada ciclo.
    SPEED <sps>          -> velocidade maxima (passos/s) dos dois eixos;
                            tambem limita JOG e RATE
    ACCEL <sps2>         -> aceleracao (passos/s^2) dos dois eixos
    JOGSPEED <sps>       -> velocidade do movimento continuo (JOG)
    STOP                 -> para tudo imediatamente
    ZERO                 -> zera a posicao atual (tubo na horizontal)
    ENABLE / DISABLE     -> liga/desliga os drivers. DISABLE para os eixos e,
                            ate o proximo ENABLE, MOVE/GOTO/JOG/RATE
                            respondem "ERR DISABLED" (motor solto nao anda,
                            entao contar passos faria a posicao ficar errada).

  Se o Arduino reiniciar (queda de energia, reset), ele imprime "READY" e a
  posicao volta a 0: o PC deve tratar isso como "posicao perdida".
*/

#include <AccelStepper.h>
#include <SoftwareSerial.h>

// ===================== CONFIGURACAO =====================
// Pinos (veja a tabela de ligacoes no README).
const uint8_t AZ_STEP  = 2, AZ_DIR  = 3, AZ_EN  = 4;
const uint8_t ALT_STEP = 5, ALT_DIR = 6, ALT_EN = 7;

// HC-06 por SoftwareSerial nos pinos 10/11: os pinos 0/1 sao do USB (Serial),
// que tambem recebe comandos e e usado para gravar o firmware.
const uint8_t BT_RX = 10;  // Arduino RX  <- HC-06 TX  (ligacao direta)
const uint8_t BT_TX = 11;  // Arduino TX  -> HC-06 RX  (USE O DIVISOR 5V->3,3V!)
const long    BT_BAUD = 9600;

// Lembrete: com microstep 1/16, 1 volta do motor = 200 * 16 = 3200 passos.
// Ajuste estes padroes depois de medir torque e vibracao.
float MAX_SPEED = 2000.0;  // velocidade maxima (passos/s)
float ACCEL     = 1000.0;  // aceleracao (passos/s^2)
float JOG_SPEED =  600.0;  // velocidade do JOG continuo (passos/s)
// =======================================================

SoftwareSerial bt(BT_RX, BT_TX);

// Estado de cada eixo. Modos: posicionamento (MOVE/GOTO, com rampa),
// JOG (velocidade fixa ate parar) ou RATE (velocidade definida pelo PC).
struct Eixo {
  AccelStepper motor;
  int   jog;       // -1, 0, +1
  bool  rateOn;
  float rate;      // passos/s, com sinal
};

Eixo az  = { AccelStepper(AccelStepper::DRIVER, AZ_STEP,  AZ_DIR),  0, false, 0.0 };
Eixo alt = { AccelStepper(AccelStepper::DRIVER, ALT_STEP, ALT_DIR), 0, false, 0.0 };

bool driversOn = false;

// Dois canais de comando: HC-06 (Bluetooth) e o cabo USB (Serial). Cada um tem
// seu buffer de linha, e a resposta sai pelo canal de onde veio o comando. Com
// isso o USB serve para testar na bancada e como alternativa ao Bluetooth.
struct Canal {
  Stream* porta;
  char buf[48];
  uint8_t len;
};

Canal canalBt  = { &bt,     {0}, 0 };
Canal canalUsb = { &Serial, {0}, 0 };
Stream* saida = &bt;     // canal do comando em atendimento

// Parada imediata e limpa. setCurrentPosition() zera a velocidade e o estado
// interno da rampa do AccelStepper; sem isso, trocar de runSpeed() (JOG/RATE)
// para run() (MOVE/GOTO) pode partir com uma velocidade velha.
void pararEixo(Eixo& e) {
  e.jog = 0;
  e.rateOn = false;
  e.rate = 0.0;
  e.motor.setCurrentPosition(e.motor.currentPosition());
}

void enableDrivers(bool on) {
  // No DRV8825 o pino EN e ativo em LOW (LOW = habilitado).
  digitalWrite(AZ_EN,  on ? LOW : HIGH);
  digitalWrite(ALT_EN, on ? LOW : HIGH);
  driversOn = on;
}

void reportPos() {
  saida->print(F("POS AZ="));
  saida->print(az.motor.currentPosition());
  saida->print(F(" ALT="));
  saida->println(alt.motor.currentPosition());
}

void handle(char* line) {
  char* cmd = strtok(line, " ");
  if (!cmd) return;

  if (!strcasecmp(cmd, "PING")) { saida->println(F("PONG")); return; }
  if (!strcasecmp(cmd, "POS?")) { reportPos(); return; }

  if (!strcasecmp(cmd, "STOP")) {
    pararEixo(az);
    pararEixo(alt);
    saida->println(F("OK STOP"));
    return;
  }
  if (!strcasecmp(cmd, "ZERO")) {
    pararEixo(az);
    pararEixo(alt);
    az.motor.setCurrentPosition(0);
    alt.motor.setCurrentPosition(0);
    saida->println(F("OK ZERO"));
    return;
  }
  if (!strcasecmp(cmd, "ENABLE")) { enableDrivers(true); saida->println(F("OK ENABLE")); return; }
  if (!strcasecmp(cmd, "DISABLE")) {
    pararEixo(az);
    pararEixo(alt);
    enableDrivers(false);
    saida->println(F("OK DISABLE"));
    return;
  }

  if (!strcasecmp(cmd, "SPEED")) {
    char* v = strtok(NULL, " ");
    if (v) { MAX_SPEED = atof(v); az.motor.setMaxSpeed(MAX_SPEED); alt.motor.setMaxSpeed(MAX_SPEED);
             saida->print(F("OK SPEED ")); saida->println(MAX_SPEED); }
    return;
  }
  if (!strcasecmp(cmd, "ACCEL")) {
    char* v = strtok(NULL, " ");
    if (v) { ACCEL = atof(v); az.motor.setAcceleration(ACCEL); alt.motor.setAcceleration(ACCEL);
             saida->print(F("OK ACCEL ")); saida->println(ACCEL); }
    return;
  }
  if (!strcasecmp(cmd, "JOGSPEED")) {
    char* v = strtok(NULL, " ");
    if (v) { JOG_SPEED = atof(v); saida->print(F("OK JOGSPEED ")); saida->println(JOG_SPEED); }
    return;
  }

  // Comandos com eixo + valor: MOVE / GOTO / JOG / RATE  <AZ|ALT>  <n>
  char* axis = strtok(NULL, " ");
  char* val  = strtok(NULL, " ");
  if (!axis || !val) { saida->print(F("ERR ")); saida->println(cmd); return; }

  Eixo* e = NULL;
  if      (!strcasecmp(axis, "AZ"))  e = &az;
  else if (!strcasecmp(axis, "ALT")) e = &alt;
  else { saida->print(F("ERR AXIS ")); saida->println(axis); return; }

  bool movimento = !strcasecmp(cmd, "MOVE") || !strcasecmp(cmd, "GOTO") ||
                   !strcasecmp(cmd, "JOG")  || !strcasecmp(cmd, "RATE");
  if (movimento && !driversOn) { saida->println(F("ERR DISABLED")); return; }

  if (!strcasecmp(cmd, "MOVE")) {
    if (e->jog || e->rateOn) pararEixo(*e);
    e->motor.move(atol(val));          // relativo, com rampa de aceleracao
    saida->println(F("OK MOVE"));
  } else if (!strcasecmp(cmd, "GOTO")) {
    if (e->jog || e->rateOn) pararEixo(*e);
    e->motor.moveTo(atol(val));        // absoluto, com rampa
    saida->println(F("OK GOTO"));
  } else if (!strcasecmp(cmd, "JOG")) {
    int d = atoi(val);
    pararEixo(*e);
    e->jog = (d > 0) ? 1 : (d < 0 ? -1 : 0);
    saida->println(F("OK JOG"));
  } else if (!strcasecmp(cmd, "RATE")) {
    if (!e->rateOn) pararEixo(*e);     // saindo de MOVE/GOTO/JOG
    e->rateOn = true;
    e->rate = atof(val);
    saida->println(F("OK RATE"));
  } else {
    saida->print(F("ERR ")); saida->println(cmd);
  }
}

void acionar(Eixo& e) {
  // setSpeed() e limitado pelo MAX_SPEED dentro do AccelStepper.
  if (e.jog != 0)  { e.motor.setSpeed(e.jog * JOG_SPEED); e.motor.runSpeed(); }
  else if (e.rateOn) { e.motor.setSpeed(e.rate);        e.motor.runSpeed(); }
  else               { e.motor.run(); }
}

void setup() {
  pinMode(AZ_EN,  OUTPUT);
  pinMode(ALT_EN, OUTPUT);
  enableDrivers(true);

  az.motor.setMaxSpeed(MAX_SPEED);   az.motor.setAcceleration(ACCEL);
  alt.motor.setMaxSpeed(MAX_SPEED);  alt.motor.setAcceleration(ACCEL);

  bt.begin(BT_BAUD);
  Serial.begin(BT_BAUD);
  bt.println(F("READY"));
  Serial.println(F("READY"));
}

// Le o que chegou num canal (nao bloqueante) e atende cada linha completa,
// respondendo pelo mesmo canal.
void lerCanal(Canal& c) {
  while (c.porta->available()) {
    char ch = c.porta->read();
    if (ch == '\n' || ch == '\r') {
      if (c.len > 0) {
        c.buf[c.len] = '\0';
        saida = c.porta;
        handle(c.buf);
        c.len = 0;
      }
    } else if (c.len < sizeof(c.buf) - 1) {
      c.buf[c.len++] = ch;
    }
  }
}

void loop() {
  // 1) le comandos do Bluetooth e do USB
  lerCanal(canalBt);
  lerCanal(canalUsb);

  // 2) aciona os motores
  acionar(az);
  acionar(alt);
}
