//+------------------------------------------------------------------+
//|                                      ResearchTelemetry.mqh       |
//| Golden Trade X v2.90.4 — append-only research telemetry         |
//+------------------------------------------------------------------+
// Research-only observability. Telemetry failures NEVER authorize a trade,
// change risk, or synthesize missing execution/outcome data. Files are written
// to Common\Files so Python tooling can ingest them without scraping journals.
// Forward-demo sessions add hourly provenance heartbeats so configuration drift
// can be detected by the offline evaluator.
//+------------------------------------------------------------------+
#property strict

class CResearchTelemetry
  {
private:
   bool            m_enabled;
   ulong           m_magic;
   long            m_login;
   string          m_symbol;
   ENUM_TIMEFRAMES m_timeframe;
   long            m_sequence;
   string          m_candidateId;
   string          m_buildId;
   string          m_configSnapshot;
   datetime        m_lastHeartbeatUtc;

   string Clean(string value)
     {
      StringReplace(value, ",", ";");
      StringReplace(value, "\r", " ");
      StringReplace(value, "\n", " ");
      return value;
     }

   string T(datetime value)
     {
      if(value <= 0) return "";
      return TimeToString(value, TIME_DATE | TIME_SECONDS);
     }

   string L(long value)
     { return IntegerToString(value); }

   string U(ulong value)
     { return IntegerToString((long)value); }

   string D(double value, int digits = 8)
     { return DoubleToString(value, digits); }

   string TradeModeText()
     {
      ENUM_ACCOUNT_TRADE_MODE mode = (ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE);
      if(mode == ACCOUNT_TRADE_MODE_DEMO) return "DEMO";
      if(mode == ACCOUNT_TRADE_MODE_REAL) return "REAL";
      return "CONTEST";
     }

   string EventId(string family, datetime when, string discriminator = "")
     {
      m_sequence++;
      string id = L(m_login) + "-" + U(m_magic) + "-" + Clean(m_symbol) + "-" +
                  family + "-" + L((long)when) + "-" + L((long)GetTickCount()) +
                  "-" + L(m_sequence);
      if(discriminator != "") id += "-" + Clean(discriminator);
      return id;
     }

   string FileName(string family, datetime when)
     {
      MqlDateTime dt;
      TimeToStruct(when > 0 ? when : TimeCurrent(), dt);
      return "GoldenTradeX_" + family + "_" + L(m_login) + "_" + U(m_magic) +
             "_" + Clean(m_symbol) + "_" + IntegerToString(dt.year) + ".csv";
     }

   int OpenAppend(string filename, string header)
     {
      bool exists = FileIsExist(filename, FILE_COMMON);
      int flags = FILE_TXT | FILE_ANSI | FILE_COMMON;
      int handle = exists
                   ? FileOpen(filename, FILE_READ | FILE_WRITE | flags)
                   : FileOpen(filename, FILE_WRITE | flags);
      if(handle == INVALID_HANDLE)
        {
         Print("ResearchTelemetry: no se pudo abrir '", filename,
               "' | Error: ", GetLastError());
         return INVALID_HANDLE;
        }

      if(!exists)
         FileWriteString(handle, header + "\n");
      else if(FileSeek(handle, 0, SEEK_END) != 0)
        {
         Print("ResearchTelemetry: FileSeek falló en '", filename,
               "' | Error: ", GetLastError());
         FileClose(handle);
         return INVALID_HANDLE;
        }
      return handle;
     }

   bool Append(string filename, string header, string line)
     {
      if(!m_enabled) return true;
      int handle = OpenAppend(filename, header);
      if(handle == INVALID_HANDLE) return false;
      FileWriteString(handle, line + "\n");
      FileFlush(handle);
      FileClose(handle);
      return true;
     }

   bool LogSessionEvent(string kind)
     {
      if(!m_enabled) return true;
      datetime serverNow = TimeCurrent();
      datetime utcNow = TimeGMT();
      if(serverNow <= 0) serverNow = utcNow;
      if(utcNow <= 0) utcNow = serverNow;

      string header =
         "EventID,ServerTime,UtcTime,Account,Magic,Symbol,Timeframe,Kind,CandidateID,BuildID,Broker,"
         "TerminalBuild,TradeMode,ServerUtcOffsetSeconds,ConfigSnapshot";
      string line = EventId("SES", serverNow, kind) + "," + T(serverNow) + "," + T(utcNow) + "," +
                    L(m_login) + "," + U(m_magic) + "," + Clean(m_symbol) + "," +
                    Clean(EnumToString(m_timeframe)) + "," + Clean(kind) + "," +
                    Clean(m_candidateId) + "," + Clean(m_buildId) + "," +
                    Clean(AccountInfoString(ACCOUNT_COMPANY)) + "," +
                    L((long)TerminalInfoInteger(TERMINAL_BUILD)) + "," + TradeModeText() + "," +
                    L((long)(serverNow - utcNow)) + "," + Clean(m_configSnapshot);
      return Append(SessionFileName(serverNow), header, line);
     }

public:
   void Init(bool enabled, ulong magic, string symbol, ENUM_TIMEFRAMES timeframe)
     {
      m_enabled = enabled;
      m_magic = magic;
      m_login = AccountInfoInteger(ACCOUNT_LOGIN);
      m_symbol = symbol;
      m_timeframe = timeframe;
      m_sequence = 0;
      m_candidateId = "";
      m_buildId = "";
      m_configSnapshot = "";
      m_lastHeartbeatUtc = 0;
     }

   bool IsEnabled() const
     { return m_enabled; }

   string SessionFileName(datetime when)
     { return FileName("sessions", when); }

   string SignalFileName(datetime when)
     { return FileName("signals", when); }

   string ExecutionFileName(datetime when)
     { return FileName("executions", when); }

   string OutcomeFileName(datetime when)
     { return FileName("outcomes", when); }

   bool StartSession(string candidateId, string buildId, string configSnapshot)
     {
      m_candidateId = candidateId;
      m_buildId = buildId;
      m_configSnapshot = configSnapshot;
      datetime utcNow = TimeGMT();
      if(utcNow <= 0) utcNow = TimeCurrent();
      m_lastHeartbeatUtc = utcNow;
      return LogSessionEvent("START");
     }

   bool Heartbeat()
     {
      if(!m_enabled) return true;
      datetime utcNow = TimeGMT();
      if(utcNow <= 0) utcNow = TimeCurrent();
      if(m_lastHeartbeatUtc > 0 && utcNow - m_lastHeartbeatUtc < 3600)
         return true;
      bool ok = LogSessionEvent("HEARTBEAT");
      if(ok) m_lastHeartbeatUtc = utcNow;
      return ok;
     }

   bool EndSession(int reason)
     {
      // The deinit reason belongs to the terminal journal, not the immutable
      // build identity. OnDeinit already logs it in GoldenTradeX.mq5.
      return LogSessionEvent("END");
     }

   bool LogSignal(datetime barTime,
                  string stage,
                  string decision,
                  string reason,
                  string direction,
                  int confidence,
                  int regime,
                  int baseScore,
                  int regimeScore,
                  int smcScore,
                  int htfScore,
                  int fibScore,
                  double atr,
                  double requestedPrice,
                  double sl,
                  double tp,
                  double initialRR,
                  double lots,
                  ulong positionId = 0,
                  ulong orderTicket = 0,
                  ulong dealTicket = 0)
     {
      if(!m_enabled) return true;
      datetime now = TimeCurrent();
      double bid = SymbolInfoDouble(m_symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(m_symbol, SYMBOL_ASK);
      double point = SymbolInfoDouble(m_symbol, SYMBOL_POINT);
      double spreadPoints = (point > 0 && ask >= bid) ? (ask - bid) / point : 0.0;

      string header =
         "EventID,EventTime,BarTime,Account,Magic,Symbol,Timeframe,Stage,Decision,Reason,Direction,"
         "Confidence,Regime,BaseScore,RegimeScore,SmcScore,HtfScore,FibScore,Bid,Ask,SpreadPoints,ATR,"
         "RequestedPrice,SL,TP,InitialRR,Lots,PositionID,OrderTicket,DealTicket";

      string line = EventId("SIG", now, stage) + "," + T(now) + "," + T(barTime) + "," +
                    L(m_login) + "," + U(m_magic) + "," + Clean(m_symbol) + "," +
                    Clean(EnumToString(m_timeframe)) + "," + Clean(stage) + "," +
                    Clean(decision) + "," + Clean(reason) + "," + Clean(direction) + "," +
                    IntegerToString(confidence) + "," + IntegerToString(regime) + "," +
                    IntegerToString(baseScore) + "," + IntegerToString(regimeScore) + "," +
                    IntegerToString(smcScore) + "," + IntegerToString(htfScore) + "," +
                    IntegerToString(fibScore) + "," + D(bid) + "," + D(ask) + "," +
                    D(spreadPoints, 3) + "," + D(atr) + "," + D(requestedPrice) + "," +
                    D(sl) + "," + D(tp) + "," + D(initialRR, 6) + "," + D(lots, 4) + "," +
                    U(positionId) + "," + U(orderTicket) + "," + U(dealTicket);
      return Append(SignalFileName(now), header, line);
     }

   bool LogOrderResult(string action,
                       string status,
                       string direction,
                       double requestedPrice,
                       double requestedSL,
                       double requestedTP,
                       double requestedVolume,
                       uint retcode,
                       int resultClass,
                       double executedPrice,
                       double executedVolume,
                       double slippagePoints,
                       ulong orderTicket,
                       ulong dealTicket,
                       ulong positionId,
                       ulong positionTicket,
                       string comment)
     {
      if(!m_enabled) return true;
      datetime now = TimeCurrent();
      string header =
         "EventID,EventTime,Account,Magic,Symbol,Action,Status,Direction,RequestedPrice,RequestedSL,"
         "RequestedTP,RequestedVolume,ServerRetcode,ResultClass,ExecutedPrice,ExecutedVolume,SlippagePoints,"
         "OrderTicket,DealTicket,PositionID,PositionTicket,DealEntry,DealReason,Profit,Commission,Swap,Fee,Comment";

      string line = EventId("EXE", now, action) + "," + T(now) + "," + L(m_login) + "," +
                    U(m_magic) + "," + Clean(m_symbol) + "," + Clean(action) + "," +
                    Clean(status) + "," + Clean(direction) + "," + D(requestedPrice) + "," +
                    D(requestedSL) + "," + D(requestedTP) + "," + D(requestedVolume, 4) + "," +
                    IntegerToString((int)retcode) + "," + IntegerToString(resultClass) + "," +
                    D(executedPrice) + "," + D(executedVolume, 4) + "," +
                    D(slippagePoints, 3) + "," + U(orderTicket) + "," + U(dealTicket) + "," +
                    U(positionId) + "," + U(positionTicket) + ",,,,,,," + Clean(comment);
      return Append(ExecutionFileName(now), header, line);
     }

   bool LogDeal(ulong dealTicket)
     {
      if(!m_enabled) return true;
      if(dealTicket == 0 || !HistoryDealSelect(dealTicket)) return false;

      datetime when = (datetime)HistoryDealGetInteger(dealTicket, DEAL_TIME);
      string symbol = HistoryDealGetString(dealTicket, DEAL_SYMBOL);
      if(symbol == "") symbol = m_symbol;
      long dealType = HistoryDealGetInteger(dealTicket, DEAL_TYPE);
      string direction = dealType == DEAL_TYPE_BUY ? "BUY" :
                         dealType == DEAL_TYPE_SELL ? "SELL" : "OTHER";
      long entry = HistoryDealGetInteger(dealTicket, DEAL_ENTRY);
      long reason = HistoryDealGetInteger(dealTicket, DEAL_REASON);
      ulong orderTicket = (ulong)HistoryDealGetInteger(dealTicket, DEAL_ORDER);
      ulong positionId = (ulong)HistoryDealGetInteger(dealTicket, DEAL_POSITION_ID);

      string header =
         "EventID,EventTime,Account,Magic,Symbol,Action,Status,Direction,RequestedPrice,RequestedSL,"
         "RequestedTP,RequestedVolume,ServerRetcode,ResultClass,ExecutedPrice,ExecutedVolume,SlippagePoints,"
         "OrderTicket,DealTicket,PositionID,PositionTicket,DealEntry,DealReason,Profit,Commission,Swap,Fee,Comment";

      string line = EventId("DEAL", when, U(dealTicket)) + "," + T(when) + "," +
                    L(m_login) + "," + U(m_magic) + "," + Clean(symbol) +
                    ",DEAL,EXECUTED," + direction + ",0,0,0,0,0,0," +
                    D(HistoryDealGetDouble(dealTicket, DEAL_PRICE)) + "," +
                    D(HistoryDealGetDouble(dealTicket, DEAL_VOLUME), 4) + ",0," +
                    U(orderTicket) + "," + U(dealTicket) + "," + U(positionId) + ",0," +
                    L(entry) + "," + L(reason) + "," +
                    D(HistoryDealGetDouble(dealTicket, DEAL_PROFIT), 2) + "," +
                    D(HistoryDealGetDouble(dealTicket, DEAL_COMMISSION), 2) + "," +
                    D(HistoryDealGetDouble(dealTicket, DEAL_SWAP), 2) + "," +
                    D(HistoryDealGetDouble(dealTicket, DEAL_FEE), 2) + "," +
                    Clean(HistoryDealGetString(dealTicket, DEAL_COMMENT));
      return Append(ExecutionFileName(when), header, line);
     }

   bool LogPositionOutcome(datetime closeTime,
                           string symbol,
                           ulong positionId,
                           string direction,
                           datetime entryTime,
                           double entryPrice,
                           double initialSL,
                           double initialTP,
                           double initialRiskPrice,
                           double initialRiskMoney,
                           double initialVolume,
                           int confidence,
                           int regime,
                           double mfeR,
                           double mfePrice,
                           datetime mfeTime,
                           double maeR,
                           double maePrice,
                           datetime maeTime,
                           double netPnl,
                           double realizedR,
                           double closePrice)
     {
      if(!m_enabled) return true;
      string header =
         "EventID,CloseTime,Account,Magic,Symbol,PositionID,Direction,EntryTime,EntryPrice,InitialSL,InitialTP,"
         "InitialRiskPrice,InitialRiskMoney,InitialVolume,Confidence,Regime,MFE_R,MFE_Price,MFE_Time,MAE_R,"
         "MAE_Price,MAE_Time,NetPnL,RealizedR,ClosePrice";

      string line = EventId("OUT", closeTime, U(positionId)) + "," + T(closeTime) + "," +
                    L(m_login) + "," + U(m_magic) + "," + Clean(symbol) + "," + U(positionId) + "," +
                    Clean(direction) + "," + T(entryTime) + "," + D(entryPrice) + "," + D(initialSL) + "," +
                    D(initialTP) + "," + D(initialRiskPrice) + "," + D(initialRiskMoney, 2) + "," +
                    D(initialVolume, 4) + "," + IntegerToString(confidence) + "," + IntegerToString(regime) + "," +
                    D(mfeR, 6) + "," + D(mfePrice) + "," + T(mfeTime) + "," + D(maeR, 6) + "," +
                    D(maePrice) + "," + T(maeTime) + "," + D(netPnl, 2) + "," + D(realizedR, 6) + "," +
                    D(closePrice);
      return Append(OutcomeFileName(closeTime), header, line);
     }
  };
//+------------------------------------------------------------------+
