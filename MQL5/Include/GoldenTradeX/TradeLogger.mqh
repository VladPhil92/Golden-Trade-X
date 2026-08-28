//+------------------------------------------------------------------+
//|                                                TradeLogger.mqh   |
//|   Golden Trade X v2.62 — Registro auditable por posición        |
//+------------------------------------------------------------------+
//  Una línea CSV por posición cerrada en Common\Files.
//
//  v2.62: RMultiple ya NO se deduce del precio del último deal. Con cierres
//  parciales eso era matemáticamente incorrecto. Ahora:
//
//       Realized R = Total Net P/L / Initial Monetary Risk
//
//  Initial Monetary Risk se reconstruye desde entry price + InitialSL +
//  volumen inicial mediante OrderCalcProfit(), respetando especificaciones
//  reales del símbolo/broker. P/L neto agrega todos los cierres de la posición,
//  incluso un cierre manual (magic 0), siempre que todas las ENTRADAS de la
//  posición pertenezcan a Golden Trade X. Si detecta mezcla de propietarios
//  en una posición netting, falla cerrado y no fabrica métricas.
//+------------------------------------------------------------------+
#property strict

class CTradeLogger
  {
private:
   bool   m_enabled;
   ulong  m_magic;

   int OpenFile(string filename)
     {
      bool exists = FileIsExist(filename, FILE_COMMON);
      int flags = FILE_TXT | FILE_ANSI | FILE_COMMON;
      int handle = exists
                   ? FileOpen(filename, FILE_READ | FILE_WRITE | flags)
                   : FileOpen(filename, FILE_WRITE | flags);
      if(handle == INVALID_HANDLE) return INVALID_HANDLE;

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
         return INVALID_HANDLE;
        }
      return handle;
     }

   bool GetEntryData(ulong positionId, string symbol,
                     double &entryPrice, double &initialSL, double &initialTP,
                     datetime &openTime, string &comment)
     {
      entryPrice = 0;
      initialSL = 0;
      initialTP = 0;
      openTime = 0;
      comment = "";
      if(!HistorySelectByPosition(positionId)) return false;

      datetime earliest = 0;
      for(int i = 0; i < HistoryDealsTotal(); i++)
        {
         ulong ticket = HistoryDealGetTicket(i);
         if(ticket == 0) continue;
         if(HistoryDealGetInteger(ticket, DEAL_MAGIC) != (long)m_magic) continue;
         if(HistoryDealGetString(ticket, DEAL_SYMBOL) != symbol) continue;

         long entry = HistoryDealGetInteger(ticket, DEAL_ENTRY);
         if(entry != DEAL_ENTRY_IN && entry != DEAL_ENTRY_INOUT) continue;

         datetime t = (datetime)HistoryDealGetInteger(ticket, DEAL_TIME);
         if(earliest != 0 && t >= earliest) continue;

         double price = HistoryDealGetDouble(ticket, DEAL_PRICE);
         if(price <= 0) continue;
         earliest = t;
         entryPrice = price;
         initialSL = HistoryDealGetDouble(ticket, DEAL_SL);
         initialTP = HistoryDealGetDouble(ticket, DEAL_TP);
         openTime = t;
         comment = HistoryDealGetString(ticket, DEAL_COMMENT);
         StringReplace(comment, ",", ";");
        }
      return entryPrice > 0;
     }

   bool GetPositionTotals(ulong positionId, double &entryVolume,
                          double &totalProfit, double &totalCommSwap)
     {
      entryVolume = 0;
      totalProfit = 0;
      totalCommSwap = 0;
      if(!HistorySelectByPosition(positionId)) return false;

      bool ownedEntry = false;
      bool foreignEntry = false;

      for(int i = 0; i < HistoryDealsTotal(); i++)
        {
         ulong ticket = HistoryDealGetTicket(i);
         if(ticket == 0) continue;
         long entry = HistoryDealGetInteger(ticket, DEAL_ENTRY);
         long magic = HistoryDealGetInteger(ticket, DEAL_MAGIC);

         if(entry == DEAL_ENTRY_IN)
           {
            if(magic == (long)m_magic)
              {
               ownedEntry = true;
               entryVolume += HistoryDealGetDouble(ticket, DEAL_VOLUME);
              }
            else
               foreignEntry = true;
           }
         else if(entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_INOUT)
           {
            // Salidas manuales/broker-side pueden tener magic distinto; si la
            // posición es inequívocamente GTX, deben formar parte del net P/L.
            totalProfit += HistoryDealGetDouble(ticket, DEAL_PROFIT);
            totalCommSwap += HistoryDealGetDouble(ticket, DEAL_COMMISSION)
                           + HistoryDealGetDouble(ticket, DEAL_SWAP)
                           + HistoryDealGetDouble(ticket, DEAL_FEE);
           }
        }

      if(foreignEntry)
        {
         Print("TradeLogger: FAIL-CLOSED — position_id=", positionId,
               " contiene entradas de otro magic/manual en cuenta netting; métricas omitidas.");
         return false;
        }
      return ownedEntry && entryVolume > 0;
     }

   double CalcInitialRiskMoney(string symbol, bool isBuy, double entryPrice,
                               double initialSL, double initialVolume)
     {
      if(entryPrice <= 0 || initialSL <= 0 || initialVolume <= 0) return 0.0;
      if(isBuy && initialSL >= entryPrice) return 0.0;
      if(!isBuy && initialSL <= entryPrice) return 0.0;

      double pnlAtStop = 0.0;
      ENUM_ORDER_TYPE type = isBuy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
      if(!OrderCalcProfit(type, symbol, initialVolume,
                          entryPrice, initialSL, pnlAtStop))
        {
         Print("TradeLogger: OrderCalcProfit no pudo reconstruir Initial Risk | symbol=",
               symbol, " error=", GetLastError());
         return 0.0;
        }
      return MathAbs(pnlAtStop);
     }

public:
   void Init(bool enabled, ulong magic)
     {
      m_enabled = enabled;
      m_magic = magic;
     }

   void LogTrade(ulong exitDealTicket)
     {
      if(!m_enabled) return;
      if(!HistoryDealSelect(exitDealTicket)) return;

      long exitType = HistoryDealGetInteger(exitDealTicket, DEAL_TYPE);
      if(exitType != DEAL_TYPE_BUY && exitType != DEAL_TYPE_SELL) return;

      ulong positionId = (ulong)HistoryDealGetInteger(exitDealTicket, DEAL_POSITION_ID);
      datetime closeTime = (datetime)HistoryDealGetInteger(exitDealTicket, DEAL_TIME);
      double closePrice = HistoryDealGetDouble(exitDealTicket, DEAL_PRICE);
      string symbol = HistoryDealGetString(exitDealTicket, DEAL_SYMBOL);

      double entryPrice, initialSL, initialTP;
      datetime openTime;
      string entryComment;
      if(!GetEntryData(positionId, symbol, entryPrice, initialSL, initialTP,
                       openTime, entryComment))
        {
         Print("TradeLogger: no se pudo reconstruir entrada GTX para position_id=", positionId);
         return;
        }

      double entryVol, totalProfit, totalCosts;
      if(!GetPositionTotals(positionId, entryVol, totalProfit, totalCosts))
         return;

      // Dirección obtenida de la ENTRADA/exit convencional. Si la salida final
      // es SELL, la posición original fue BUY; si es BUY, fue SELL.
      bool isBuy = (exitType == DEAL_TYPE_SELL);
      string typeStr = isBuy ? "BUY" : "SELL";
      double initialRiskMoney = CalcInitialRiskMoney(symbol, isBuy, entryPrice,
                                                     initialSL, entryVol);
      double netPnl = totalProfit + totalCosts;
      double realizedR = initialRiskMoney > 0 ? netPnl / initialRiskMoney : 0.0;
      if(initialRiskMoney <= 0)
         Print("TradeLogger: Initial Risk inválido para position_id=", positionId,
               " — RMultiple=0.0 (fail-safe, no inventado).");

      MqlDateTime dt;
      TimeToStruct(closeTime, dt);
      long login = AccountInfoInteger(ACCOUNT_LOGIN);
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
        "%04d-%02d-%02d,%02d:%02d:%02d,%s,%s,%s,%.2f,%.5f,%.5f,%.5f,%.5f,%.2f,%.2f,%.4f,"
        "%04d-%02d-%02d,%02d:%02d:%02d,%s\n",
        dt.year, dt.mon, dt.day, dt.hour, dt.min, dt.sec,
        IntegerToString((long)positionId), symbol, typeStr,
        entryVol, entryPrice, initialSL, initialTP, closePrice,
        totalProfit, totalCosts, realizedR,
        odt.year, odt.mon, odt.day, odt.hour, odt.min, odt.sec,
        entryComment
      );

      FileWriteString(handle, line);
      FileClose(handle);
     }
  };
//+------------------------------------------------------------------+
