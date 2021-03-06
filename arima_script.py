import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import itertools
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller
from datetime import datetime, timedelta
from dateutil.relativedelta import *
import statsmodels.tsa.api as smt
import seaborn as sns
from sklearn.metrics import mean_squared_error
import pickle
from start_script import *

#function to start/end dates for train and test
def find_dates(building_id, length=1, total_length=30, final_date=None):
    start_train, end_test = find_egauge_dates(building_id, total_length)
    time_delta_1 = timedelta(days=length)
    time_delta_2 = timedelta(hours=1)
    end_train = end_test - time_delta_1
    start_test = end_train + time_delta_2
    start_train = str(start_train)
    end_train = str(end_train)
    start_test = str(start_test)
    end_test = str(end_test)

    return start_train, end_train, start_test, end_test


#function to create training and testing set
def create_train_test(data, start_train, end_train, start_test, end_test, test_length=24):

    df_train = data.loc[start_train:end_train, :]
    df_test = data.loc[start_test:end_test, :]

    start = datetime.strptime(start_test, '%Y-%m-%d %H:%M:%S')
    date_list = [start + relativedelta(hours=x) for x in range(0,test_length)]
    future = pd.DataFrame(index=date_list, columns= df_train.columns)
    df_train = pd.concat([df_train, future])

    return df_train, df_test


#function to find optimal parameters and resulting AIC score
def gridsearch_arima(y, exog=None):

    p = d = q = range(0, 2)
    pdq = list(itertools.product(p, d, q))
    seasonal_pdq = [(x[0], x[1], x[2], 24) for x in list(itertools.product(p, d, q))]

    low_aic = [0,0,50000]

    for param in pdq:
        for param_seasonal in seasonal_pdq:
            try:
                model = sm.tsa.statespace.SARIMAX(y,
                                                  exog=exog,
                                                order=param,
                                                seasonal_order=param_seasonal,
                                                enforce_stationarity=False,
                                                enforce_invertibility=False)
                results = model.fit()
                if results.aic < low_aic[2]:
                    low_aic = [param, param_seasonal, results.aic]

#                 print('ARIMA{}x{}24 - AIC:{}'.format(param, param_seasonal, results.aic))
            except:
                continue
    return low_aic



#function to add all exogenous variables
def create_exog_endo(data, weather, building_id, length=1, total_length=30):

    start_train, end_train, start_test, end_test = find_dates(building_id, length, total_length)
    df_train, df_test = create_train_test(data, start_train, end_train, start_test, end_test, 24*length)

    car_charge = mean_car_charge(data, start_train,end_train)

    df_train['Time_Index'] = df_train.index.weekday_name+ df_train.index.hour.astype(str)
    df_train['Temperature'] = weather.loc[start_train:end_test, 'temperature']
    df_train['Humidity'] = weather.loc[start_train:end_test, 'humidity']

    for time in df_train.loc[start_test:end_test,:].index:
        df_train.loc[time,'car1'] = car_charge[df_train.loc[time,'Time_Index']]

    #fill missing values with mean
    df_train['Temperature'] = df_train.Temperature.fillna(np.mean(df_train['Temperature']))
    df_train['Humidity'] = df_train.Humidity.fillna(np.mean(df_train['Humidity']))

    exogenous = df_train.loc[start_train:,['Temperature','Humidity','car1']].astype(float)
    endogenous = df_train.loc[:,'Hourly_Usage'].astype(float)

    return df_train, exogenous, endogenous



#function to fit arima model without exogenous variables
def fit_arima(data, building_id, length=1, total_length=30):

    start_train, end_train, start_test, end_test = find_dates(building_id, length, total_length)
    df_train, df_test = create_train_test(data, start_train, end_train, start_test, end_test, 24*length)

    y_train = df_train.Hourly_Usage
    low_aic = gridsearch_arima(y_train)

    arima = sm.tsa.statespace.SARIMAX(y_train,
                                  trend=None,
                                  order=low_aic[0],
                                  seasonal_order=low_aic[1],
                                  enforce_stationarity=False,
                                  enforce_invertibility=False)

#     arima = sm.tsa.statespace.SARIMAX(y_train,
#                                   trend=None,
#                                   order=(1,0,1),
#                                   seasonal_order=(0,1,1,24),
#                                   enforce_stationarity=False,
#                                   enforce_invertibility=False)
    results = arima.fit()

    return results



#function to fit SARIMAX model with create_exog_endo
def fit_exog_arima(exogenous, endogenous):

    low_aic = gridsearch_arima(endogenous,exogenous)
    arima_model = sm.tsa.statespace.SARIMAX(endog=endogenous,
                                  exog = exogenous,
                                  trend=None,
                                  order=low_aic[0],
                                  seasonal_order=low_aic[1],
                                  enforce_stationarity=False,
                                  enforce_invertibility=False)
    arima_exog_results = arima_model.fit()

    return arima_exog_results



# define helper plot function for visualization
def acf_pacf_plots(data, lags=None):
    layout = (1, 3)
    raw  = plt.subplot2grid(layout, (0, 0))
    acf  = plt.subplot2grid(layout, (0, 1))
    pacf = plt.subplot2grid(layout, (0, 2))

    data.plot(ax=raw)
    smt.graphics.plot_acf(data, lags=lags, ax=acf)
    smt.graphics.plot_pacf(data, lags=lags, ax=pacf)
    sns.despine()
    plt.tight_layout()


#function to forecast with fitted model, returns MSE and RMSE
def add_forecast(model, test, train, start_time, end_time):

    train['forecast'] = model.predict(start=start_time, end=end_time)
    y_true = test.loc[start_time:end_time, 'Hourly_Usage']
    y_pred = train.loc[start_time:end_time, 'forecast']
    train.loc[start_time:end_time, 'Hourly_Usage'] = test.loc[start_time:end_time, 'Hourly_Usage']

    mse = mean_squared_error(y_true, y_pred)
    rmse = np.sqrt(mse)

    return mse, rmse




def plot_forecast(data, datapoints):
    fig = plt.figure(figsize=(16,8))
    plt.plot(data['Hourly_Usage'][datapoints:])
    plt.plot(data['forecast'])
    plt.legend()

