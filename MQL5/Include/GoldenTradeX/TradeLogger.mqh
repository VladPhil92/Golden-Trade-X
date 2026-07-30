//+------------------------------------------------------------------+
//|                                                TradeLogger.mqh   |
//|   Golden Trade X — Registro de operaciones en CSV               |
//+------------------------------------------------------------------+
//  Escribe una línea CSV por cada posición cerrada en:
//    <Terminal_Files>/GoldenTradeX_{login}_{symbol}_{year}.csv
//
//  Columnas: CloseDate, CloseTime, PositionID, Symbol, Type, Lots,
//            OpenPrice, InitialSL, InitialTP, ClosePrice,
//            ProfitLoss, Commission, RMultiple,
//            OpenDate, OpenTime, Comment          (v2.50)
//
//  v2.50: OpenDate/OpenTime permiten construir features SIN leakage temporal
//  (la hora de cierre no se conoce al decidir la entrada) y Comment lleva
//  el Confidence Score y el régimen ("GoldenTradeX|Conf=72|Reg=TRENDING_BULL")
//  que consume scripts/ml_pipeline.py.
//
//  Uso desde OnTradeTransaction del EA principal:
//    tradeLogger.LogTrade(dealTicket);
//+------------------------------------------------------------------+
#property strict

class CTradeLogger
  {
private:
   bool   m_enabled;
   ulong  m_magic;

   // Calcula el R-múltiplo: +1.5 = ganó 1.5R, -1.0 = perdió 1R
   double CalcRMultiple(bool isBuy, double entry, double close, double initialSL)
     {
      double slDist = MathAbs(entry - initialSL);
      if(slDist <= 0) return(0);
      return(isBuy ? (close - entry) / slDist
                   : (entry - close) / slDist);
     }

   // Abre o crea el archivo CSV, escribiendo el header si es nuevo
   int OpenFile(string filename)
     {
      bool exists = FileIsExist(filename, FILE_COMMON);
      int flags   = FILE_TXT | FILE_ANSI | FILE_COMMON;

      int handle = exists
                   ? FileOpen(filename, FILE_READ | FILE_WRITE | flags)
                   : FileOpen(filename, FILE_WRITE | flags);

      if(handle == INVALID_HANDLE) return(INVALID_HANDLE);

      if(!exists)
         FileWriteString(handle,
                         "CloseDate,CloseTime,PositionID,Symbol,Type,"
                         "Lots,OpenPrice,InitialSL,InitialTP,ClosePrice,"
                         "ProfitLoss,Commission,RMultiple,"
                         "OpenDate,OpenTime,Comment\n");
      else if(FileSeek(handle, 0, SEEK_END) != 0)
        {
         Print("TradeLogger: FileSeek falló en '", filename, "' | Error: ", GetLastError());
         FileClose(handle);
         return(INVALID_HANDLE);
        }

      return(handle);
     }

   // Busca el deal de entrada de una posición para obtener precio, niveles,
   // hora de apertura y comment (v2.50)
   bool GetEntryData(ulong positionId, double &entryPrice,
                     double &initialSL, double &initialTP,
                     datetime &openTime, string &comment)
     {
      entryPrice = 0; initialSL = 0; initialTP = 0; openTime = 0; comment = "";
      if(!HistorySelectByPosition(positionId)) return(false);

      for(int i = 0; i < HistoryDealsTotal(); i++)
        {
         ulong ticket = HistoryDealGetTicket(i);
         if(ticket == 0) continue;
         if(HistoryDealGetInteger(ticket, DEAL_ENTRY) != DEAL_ENTRY_IN) continue;
         entryPrice = HistoryDealGetDouble(ticket, DEAL_PRICE);
         initialSL  = HistoryDealGetDouble(ticket, DEAL_SL);
         initialTP  = HistoryDealGetDouble(ticket, DEAL_TP);
         openTime   = (datetime)HistoryDealGetInteger(ticket, DEAL_TIME);
         comment    = HistoryDealGetString(ticket, DEAL_COMMENT);
         // El CSV usa coma como separador: sanear el comment
         StringReplace(comment, ",", ";");
         return(true);
        }
      return(false);
     }

public:
   void Init(bool enabled, ulong magic)
     {
      m_enabled = enabled;
      m_magic   = magic;
     }

   //--- Registrar un deal de cierre en el CSV
   void LogTrade(ulong exitDealTicket)
     {
      if(!m_enabled) return;
      if(!HistoryDealSelect(exitDealTicket)) return;

      // Verificar que el deal pertenece a este EA
      if(HistoryDealGetInteger(exitDealTicket, DEAL_MAGIC) != (long)m_magic) return;

      long exitType = HistoryDealGetInteger(exitDealTicket, DEAL_TYPE);
      if(exitType != DEAL_TYPE_BUY && exitType != DEAL_TYPE_SELL) return;

      // Datos del deal de salida
      ulong    positionId = HistoryDealGetInteger(exitDealTicket, DEAL_POSITION_ID);
      datetime closeTime  = (datetime)HistoryDealGetInteger(exitDealTicket, DEAL_TIME);
      double   lots       = HistoryDealGetDouble(exitDealTicket, DEAL_VOLUME);
      double   closePrice = HistoryDealGetDouble(exitDealTicket, DEAL_PRICE);
      double   profit     = HistoryDealGetDouble(exitDealTicket, DEAL_PROFIT);
      double   commission = HistoryDealGetDouble(exitDealTicket, DEAL_COMMISSION);
      string   symbol     = HistoryDealGetString(exitDealTicket, DEAL_SYMBOL);

      // Datos del deal de entrada
      double   entryPrice, initialSL, initialTP;
      datetime openTime;
      string   entryComment;
      GetEntryData(positionId, entryPrice, initialSL, initialTP,
                   openTime, entryComment);

      // BUY position = exited by a SELL deal; SELL position = exited by a BUY deal
      bool   isBuy   = (exitType == DEAL_TYPE_SELL);
      double rMult   = CalcRMultiple(isBuy, entryPrice, closePrice, initialSL);
      string typeStr = isBuy ? "BUY" : "SELL";

      MqlDateTime dt;
      TimeToStruct(closeTime, dt);

      // Nombre de archivo incluye cuenta, símbolo y año para evitar archivos gigantes
      long   login    = AccountInfoInteger(ACCOUNT_LOGIN);
      string filename = StringFormat("GoldenTradeX_%d_%s_%d.csv",
                                     (int)login, symbol, dt.year);

      int handle = OpenFile(filename);
      if(handle == INVALID_HANDLE)
        {
         Print("TradeLogger: no se pudo abrir '", filename, "' | Error: ", GetLastError());
         return;
        }

      MqlDateTime odt;
      TimeToStruct(openTime, odt);

      string line = StringFormat(
        "%04d-%02d-%02d,%02d:%02d:%02d,%s,%s,%s,%.2f,%.5f,%.5f,%.5f,%.5f,%.2f,%.2f,%.2f,"
        "%04d-%02d-%02d,%02d:%02d:%02d,%s\n",
        dt.year, dt.mon, dt.day, dt.hour, dt.min, dt.sec,
        IntegerToString((long)positionId), symbol, typeStr,
        lots, entryPrice, initialSL, initialTP, closePrice,
        profit, commission, rMult,
        odt.year, odt.mon, odt.day, odt.hour, odt.min, odt.sec,
        entryComment
      );

      FileWriteString(handle, line);
      FileClose(handle);
     }
  };
//+------------------------------------------------------------------+
