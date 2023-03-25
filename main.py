import pandas as pd
import numpy as np
import panel as pn
from bokeh.models import ColumnDataSource, DataTable, TableColumn
import hvplot.pandas

# file names for imports
rate_puf = "rate_puf.csv"
benefits_cost_sharing_puf = "benefits_cost_sharing_puf.csv"
plan_attributes_puf = "plan_attributes_puf.csv"

# function to calculate the maximum percentage of annual income that goes to the monthly rate
def max_percent_of_income(income_percentage):
    if 1.33 <= income_percentage < 1.5:
        return 0.0
    elif 1.5 <= income_percentage < 2.0:
        return 0 + (0.02 - 0) * ((income_percentage - 1.5) / (2.0 - 1.5))
    elif 2.0 <= income_percentage < 2.5:
        return 0.02 + (0.04 - 0.02) * ((income_percentage - 2.0) / (2.5 - 2.0))
    elif 2.5 <= income_percentage < 3.0:
        return 0.04 + (0.06 - 0.04) * ((income_percentage - 2.5) / (3.0 - 2.5))
    elif 3.0 <= income_percentage < 4.0:
        return 0.06 + (0.085 - 0.06) * ((income_percentage - 3.0) / (4.0 - 3.0))
    else:
        return 0

# calculate the second-lowest in a series of values, and return just the lowest if there is only one value
def get_second_lowest(x):
    try:
        return sorted(x)[1]
    except:
        return sorted(x)[0]

def update_rates_table(age, state, rating_area, metal_level, csr_variation, income):
    global df_rates
    global df_changes
    global rates_table

    # always filter for state, rating_area
    filtered_df = df_rates[df_rates['StateCode'].isin(state) & df_rates['RatingAreaId'].isin(rating_area)]

    # filter rate changes for state, rating_area
    filtered_df_changes = df_changes[df_changes['StateCode'].isin(state) & df_changes['RatingAreaId'].isin(rating_area)]

    # calculate rate changes for current selection
    # show filtered_df_changes for IssuerMarketPlaceMarketingName UnitedHealthcare
    filtered_df = multiply_rates(filtered_df, filtered_df_changes)

    # calculate benchmark rates for current selection
    filtered_df = update_benchmark_rates(filtered_df)

    # filter for metal_level
    if metal_level:
        filtered_df = filtered_df[filtered_df['MetalLevel'].isin(metal_level)]

    # add Income column with values ranging from 130% to 400% of the Federal Poverty Line (FPL)
    income_percentages = np.arange(1.3, 4.1, 0.1)
    filtered_df = filtered_df.reindex(filtered_df.index.repeat(len(income_percentages)))
    filtered_df['Income'] = [round(x, 1) for x in income_percentages.tolist()] * (len(filtered_df) // len(income_percentages))

    # calculate the maximum monthly rate based on the Income percentage
    filtered_df['MaxMonthlyRate'] = (filtered_df['Income'] * 13500 * filtered_df['Income'].apply(max_percent_of_income) / 12).round(2)

    # calculate the Subsidy for each row as the difference between the benchmark IndividualRate and the MaxMonthlyRate
    filtered_df['Subsidy'] = filtered_df['IndividualRate_Benchmark'] - filtered_df['MaxMonthlyRate']
    filtered_df['Subsidy'] = filtered_df['Subsidy'].where(filtered_df['Subsidy'] > 0, 0).round(2)

    # calculate the Net Monthly Rate for each row, but has to be above 0
    filtered_df['NetMonthlyRate'] = filtered_df['IndividualRate'] - filtered_df['Subsidy']
    filtered_df['NetMonthlyRate'] = filtered_df['NetMonthlyRate'].where(filtered_df['NetMonthlyRate'] > 0, 0)

    # do the same, but on IndividualRate_New
    filtered_df['Subsidy_New'] = filtered_df['IndividualRate_New_Benchmark'] - filtered_df['MaxMonthlyRate']
    filtered_df['Subsidy_New'] = filtered_df['Subsidy_New'].where(filtered_df['Subsidy_New'] > 0, 0).round(2)

    filtered_df['NetMonthlyRate_New'] = filtered_df['IndividualRate_New'] - filtered_df['Subsidy_New']
    filtered_df['NetMonthlyRate_New'] = filtered_df['NetMonthlyRate_New'].where(filtered_df['NetMonthlyRate_New'] > 0, 0)

    # filter for income, age, csr_variation
    if income:
        filtered_df = filtered_df[filtered_df['Income'].isin(income)]
    if age:
        filtered_df = filtered_df[filtered_df['Age'].isin(age)]
    if csr_variation:
        filtered_df = filtered_df[filtered_df['CSRVariationType'].isin(csr_variation)]

    # only show certain columns
    columns_to_show = ['StateCode', 'RatingAreaId', 'IssuerMarketPlaceMarketingName', 'PlanMarketingName', 'PlanType', 'MetalLevel', 'CSRVariationType', 'Age', 'Income', 'NetMonthlyRate', 'NetMonthlyRate_New', 'IndividualRate', 'IndividualRate_Benchmark', 'IndividualRate_New', 'IndividualRate_New_Benchmark', 'MaxMonthlyRate', 'Subsidy', 'Subsidy_New']
    filtered_df = filtered_df[columns_to_show]

    # round Income to one decimal place
    filtered_df['Income'] = filtered_df['Income'].apply(lambda x: round(x, 2))

    # NetMonthlyRate and _New round to two decimal places
    filtered_df['NetMonthlyRate'] = filtered_df['NetMonthlyRate'].apply(lambda x: round(x, 2))
    filtered_df['NetMonthlyRate_New'] = filtered_df['NetMonthlyRate_New'].apply(lambda x: round(x, 2))

    # show data in rates_table
    rates_table.columns = [TableColumn(field=c, title=c) for c in filtered_df.columns]
    rates_source.data = filtered_df

# calculates the new rates after applying rate changes
def multiply_rates(rates, changes):
    # calculate IndividualRate_New in rates as IndividualRate * (1 + Percentage) matching on StateCode, RatingAreaId, MetalLevel, IssueMarketPlaceMarketingName
    rates = rates.merge(changes, how='left', on=['StateCode', 'RatingAreaId', 'MetalLevel', 'IssuerMarketPlaceMarketingName'])
    rates['IndividualRate_New'] = rates['IndividualRate'] * (1 + rates['Percentage'] / 100)

    # if there are no rate changes for a row, then IndividualRate_New = IndividualRate
    rates['IndividualRate_New'].fillna(rates['IndividualRate'], inplace=True)

    rates.drop('Percentage', axis=1, inplace=True)

    return rates

# calculates the benchmark silver rates for each row in the rates table
def update_benchmark_rates(data):
    # calculate the benchmark IndividualRate for each row: second-lowest IndividualRate for each Age, StateCode, RatingAreaId, for MetalLevel = Silver and CsrVariationType = 'Standard Silver On Exchange Plan'
    benchmark = data[(data['MetalLevel'] == 'Silver') & (data['CSRVariationType'] == 'Standard Silver On Exchange Plan')].groupby(['Age', 'StateCode', 'RatingAreaId']).agg(IndividualRate=('IndividualRate',get_second_lowest), IndividualRate_New=('IndividualRate_New',get_second_lowest)).reset_index()

    # if there is a column benchmark, then drop it
    if 'IndividualRate_Benchmark' in data.columns:
        data.drop('IndividualRate_Benchmark', axis=1, inplace=True)
        data.drop('IndividualRate_New_Benchmark', axis=1, inplace=True)

    # join the benchmark IndividualRate back to the main dataframe, or update the existing column
    data = data.merge(benchmark, on=['Age', 'StateCode', 'RatingAreaId'], suffixes=('', '_Benchmark'))

    return data

# function to read rate changes edited in the insurer rate change table and store them in a dataframe
def get_insurer_ratechange_from_table(states, rating_areas):
    global insurer_rates_table
    global df_changes

    # get rate changes from the table
    pivot_data = insurer_rates_table.value.reset_index()

    melted_df = pd.melt(pivot_data, id_vars=['IssuerMarketPlaceMarketingName'], value_vars=['Bronze', 'Expanded Bronze', 'Silver', 'Gold', 'Platinum'], var_name='MetalLevel', value_name='Percentage')
    # add columns for state and rating_area and fill with the first state and rating_area in the list
    melted_df['StateCode'] = states[0]
    melted_df['RatingAreaId'] = rating_areas[0]

    # now concat to df_changes
    df_changes = pd.concat([df_changes, melted_df], ignore_index=True)

    # drop duplicates and only keep the last one, so that any previously stored rate change gets overwritten
    df_changes.drop_duplicates(subset=['StateCode', 'RatingAreaId', 'MetalLevel', 'IssuerMarketPlaceMarketingName'], keep='last', inplace=True)
    df_changes.reset_index()

    # make sure Percentage column is float
    df_changes['Percentage'] = df_changes['Percentage'].astype(float)

# function to update insurer table
def get_table_from_insurer_ratechange(state, rating_area):
    global df_rates
    global df_changes
    global insurer_rates_table

    # get rate changes from df_changes for current state and rating_area
    rates = df_changes[(df_changes['StateCode'].isin(state)) & (df_changes['RatingAreaId'].isin(rating_area))]

    # if rates is empty, set it up with the default values
    if rates.empty:
        rates = pd.DataFrame(columns=['MetalLevel', 'IssuerMarketPlaceMarketingName', 'Percentage'])
        # create entry for each metal level, each insurer, and percentage = 0
        metals = ['Bronze', 'Expanded Bronze', 'Silver', 'Gold', 'Platinum']
        insurers = df_rates[df_rates['StateCode'].isin(state) & df_rates['RatingAreaId'].isin(rating_area)]['IssuerMarketPlaceMarketingName'].unique()
        for metal in metals:
            for insurer in insurers:
                # use concat to add a new row to the dataframe
                rates = pd.concat([rates, pd.DataFrame([[metal, insurer, 0]], columns=['MetalLevel', 'IssuerMarketPlaceMarketingName', 'Percentage'])])

    # update the insurer_rates_table with the new insurer_table data
    insurer_rates_table.value = rates.pivot(index="IssuerMarketPlaceMarketingName", columns="MetalLevel", values="Percentage")


# df stores the rates for all insurers for all states and rating areas
df_rates = []
# df_changes table stores the rate increases/decreases for each insurer
df_changes = []

# initialize df_changes
df_changes = pd.DataFrame(columns=['StateCode', 'RatingAreaId', 'MetalLevel', 'IssuerMarketPlaceMarketingName', 'Percentage'])

# load Rate_PUF
columns_to_read = ['PlanId', 'StateCode', 'RatingAreaId', 'Tobacco', 'Age', 'IndividualRate', 'IndividualTobaccoRate']
df_rates_original = pd.read_csv(rate_puf, usecols=columns_to_read)

# load Benefits_Cost_Sharing_PUF
#columns_to_read = ['PlanId']
#df_benefits_cost_sharing = pd.read_csv(benefits_cost_sharing_puf, usecols=columns_to_read)

# load Plan_Attributes_PUF
columns_to_read = ['IssuerId', 'IssuerMarketPlaceMarketingName', 'StandardComponentId', 'PlanMarketingName', 'PlanType', 'MetalLevel', 'CSRVariationType']
df_plan_attributes = pd.read_csv(plan_attributes_puf, usecols=columns_to_read)

# look up metal level from df_plan_attributes and add as column to df_rates, but only get one row per StandardComponentId and MetalLevel
df_plan_attributes_lookup = df_plan_attributes.drop_duplicates(subset=['StandardComponentId', 'MetalLevel'])[['StandardComponentId', 'MetalLevel']]

# join metal level with the main rates table
df_rates = df_rates_original.merge(df_plan_attributes_lookup, left_on='PlanId', right_on='StandardComponentId', how='left')

# only keep plans with metal level of Bronze, Expanded Bronze, Silver, Gold, or Platinum
df_rates = df_rates[df_rates['MetalLevel'].isin(['Bronze', 'Silver', 'Gold', 'Platinum', 'Expanded Bronze', 'Catastrophic'])]

# join all columns from df_plan_attributes to df by joining on PlanId and StandardComponentId
df_rates = df_rates.merge(df_plan_attributes.loc[:, df_plan_attributes.columns != 'MetalLevel'], left_on="PlanId", right_on="StandardComponentId")

# create the selector widgets for age, state, rating area, metal level, CSR variation
age_widget = pn.widgets.MultiChoice(name='Age', options=df_rates['Age'].unique().tolist())
state_widget = pn.widgets.MultiChoice(name='StateCode', options=df_rates['StateCode'].unique().tolist())
rating_area_widget = pn.widgets.MultiChoice(name='RatingAreaId', options=df_rates['RatingAreaId'].unique().tolist())
metal_level_widget = pn.widgets.MultiChoice(name='MetalLevel', options=df_rates['MetalLevel'].unique().tolist())
csr_variation_widget = pn.widgets.MultiChoice(name='CSRVariationType', options=df_rates['CSRVariationType'].unique().tolist())

# create income multichoice widget which has values ranging from 130% to 400% of the Federal Poverty Line (FPL), rounded to 1 decimal place
income_widget = pn.widgets.MultiChoice(name='Income', options=[round(x, 1) for x in np.arange(1.3, 4.1, 0.1).tolist()])

# make the widgets less wide
age_widget.width = 150
state_widget.width = 150

# calculate button shows all insurers and rates in the table, update button stores the rate changes per insurer in df_changes
calculate_button = pn.widgets.Button(name='Update Plans', button_type='primary')
update_button = pn.widgets.Button(name='Update Rate Changes', button_type='primary')

# pass the state and rating_area widgets to the update_rates function, and get the rate changes in the insurer_table
update_button.on_click(
    lambda event: get_insurer_ratechange_from_table(state_widget.value if state_widget.value else state_widget.options, rating_area_widget.value if rating_area_widget.value else rating_area_widget.options)
)

calculate_button.on_click(
    lambda event: update_rates_table(age_widget.value, state_widget.value, rating_area_widget.value, metal_level_widget.value, csr_variation_widget.value, income_widget.value)
)

# create the table that shows the rate changes for each insurer, make it editable and it updates automatically
insurer_rates_table = pn.widgets.DataFrame(
    name='Insurer Rate Changes',
    auto_edit=True,
    editable=True,
    row_height=23,
    autosize_mode='fit_columns',
    fit_columns=True,
    width=500,
    height=500
)

# create the table that shows the plans, but keep it empty for now
rates_source = ColumnDataSource(data=dict())
rates_table = DataTable(source=rates_source, autosize_mode='fit_viewport', index_position=None)

# when the state or rating_area widgets are changed, update the insurer table
state_widget.param.watch(lambda *events: get_table_from_insurer_ratechange(state_widget.value if state_widget.value else state_widget.options, rating_area_widget.value if rating_area_widget.value else rating_area_widget.options), 'value')
rating_area_widget.param.watch(lambda *events: get_table_from_insurer_ratechange(state_widget.value if state_widget.value else state_widget.options, rating_area_widget.value if rating_area_widget.value else rating_area_widget.options), 'value')

app = pn.Column(
    # show text in bold
    pn.pane.Markdown('## Rates', style={'font-weight': 'bold'}),
    pn.Row(state_widget, rating_area_widget, metal_level_widget, csr_variation_widget),
    pn.Row(age_widget, income_widget, calculate_button),
    pn.Row(rates_table),
    pn.layout.Divider(),
    pn.pane.Markdown("## Rate Increases by Insurer", style={'font-weight': 'bold'}),
    pn.Row(insurer_rates_table, update_button)
)

app.servable()

# run with panel serve main.py